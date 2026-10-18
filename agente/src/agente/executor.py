"""A ponte: traduz Task A2A ↔ tool do MCP, com pausa, retomada, recusa e falha.

Regras (decisões D1–D6 da correção de conformidade):
- Erro de parâmetro (formato do pedido, data que não é ISO 8601) é rejeitado antes da Task, com `-32602` (middleware).
- Falha durante a execução (inclusive `isError` da tool e erro do servidor MCP) termina a Task em `FAILED`.
- A mensagem relevante de cada estado vai também para `history`, via estado intermediário `WORKING`.
- A pendência é reivindicada atomicamente: só uma continuação por pausa; as demais recebem erro sem mudar o estado.
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any

from a2a.server.agent_execution import AgentExecutor
from a2a.server.tasks import TaskUpdater
from a2a.types import Part
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import A2AError, UnsupportedOperationError
from mcp_types import InputRequiredResult

from . import mcp_cliente
from .pedido import parse_pedido, valor_escolha

log = logging.getLogger(__name__)
FERRAMENTA = "reservar_sala"
MSG_SEM_PAUSA = "Esta Task não tem pausa pendente: outra continuação já está em andamento ou a Task já terminou."
MSG_FALHA_INTERNA = "Falha interna ao executar a reserva."


class FalhaDeExecucao(Exception):
    """Falha durante a execução da Task: vira `TASK_STATE_FAILED` com a mensagem."""


def _campo(obj: Any, nome: str) -> Any:
    return obj.get(nome) if isinstance(obj, dict) else getattr(obj, nome, None)


def _trace_do_cabecalho(headers: dict) -> str | None:
    tp = headers.get("traceparent") or ""
    partes = tp.split("-")
    if len(partes) == 4 and len(partes[1]) == 32:
        return partes[1]
    return None


def _alternativas(requisicao: dict) -> list[str]:
    elicit = next(iter(requisicao.values()))
    if hasattr(elicit, "model_dump"):
        elicit = elicit.model_dump(by_alias=True, exclude_none=True)
    return list(elicit["params"]["requestedSchema"]["properties"]["sala"]["enum"])


def _versao_politica(texto: str) -> str:
    primeira = texto.splitlines()[0] if texto else ""
    if not primeira.startswith("versao:"):
        raise FalhaDeExecucao("Política de uso sem versão na primeira linha.")
    return primeira.split(":", 1)[1].strip()


def _valida_argumentos(schema: dict, argumentos: dict) -> None:
    obrigatorios = (schema or {}).get("required", [])
    faltando = [campo for campo in obrigatorios if campo not in argumentos]
    if faltando:
        raise FalhaDeExecucao(f"Ferramenta {FERRAMENTA} exige: {', '.join(faltando)}.")


async def _mcp(aguardavel):
    """Converte erro do servidor MCP em falha de execução da Task."""
    try:
        return await aguardavel
    except FalhaDeExecucao:
        raise
    except A2AError:
        raise
    except Exception as exc:
        mensagem = getattr(exc, "message", None) or str(exc)
        raise FalhaDeExecucao(f"Falha no servidor MCP: {mensagem}") from exc


class ExecutorReserva(AgentExecutor):
    def __init__(self, cliente: mcp_cliente.ClienteMcp, pendencias: dict):
        self.cliente = cliente
        self.pendencias = pendencias  # task_id -> dados da pausa

    async def execute(self, context, event_queue):
        task_id = context.task_id
        contexto = context.current_task.context_id if context.current_task is not None else context.context_id
        texto = context.get_user_input().strip()
        headers = (context.call_context.state or {}).get("headers", {}) if context.call_context else {}
        up = TaskUpdater(event_queue, task_id, contexto)
        try:
            if context.current_task is None:
                cabecalho = _trace_do_cabecalho(headers)
                tarefa = pb.Task(id=task_id, context_id=contexto)
                tarefa.status.state = pb.TASK_STATE_SUBMITTED
                if context.message is not None:
                    tarefa.status.message.CopyFrom(context.message)
                await event_queue.enqueue_event(tarefa)
                await up.start_work()
                await self._novo_pedido(up, task_id, texto, cabecalho)
                return
            # Reivindicação atômica: o pop acontece antes de qualquer atualização de estado.
            pausa = self.pendencias.pop(task_id, None)
            if pausa is None:
                raise UnsupportedOperationError(message=MSG_SEM_PAUSA)
            trace = pausa["trace"]
            cabecalho = _trace_do_cabecalho(headers)
            if cabecalho and not pausa["trace_do_cliente"]:
                trace, pausa["trace"], pausa["trace_do_cliente"] = cabecalho, cabecalho, True
            # O SDK registra no history a mensagem do usuário e move a pausa do status; o task store tira as repetições.
            await up.start_work()
            await self._continuar(up, task_id, texto, pausa)
        except A2AError:
            raise
        except FalhaDeExecucao as falha:
            await self._falhar(up, str(falha))
        except Exception:
            log.exception("Falha inesperada na execução da Task %s", task_id)
            await self._falhar(up, MSG_FALHA_INTERNA)

    async def cancel(self, context, event_queue):
        raise NotImplementedError("cancelamento não é exigido pelo desafio")

    def _tp(self, trace: str) -> str:
        return mcp_cliente.traceparent_para(trace, secrets.token_hex(8))

    async def _novo_pedido(self, up, task_id, texto, cabecalho):
        args = parse_pedido(texto)
        trace = cabecalho or secrets.token_hex(16)
        ferramentas = await _mcp(self.cliente.listar_ferramentas(self._tp(trace)))
        schema = ferramentas.get(FERRAMENTA)
        if schema is None:
            raise FalhaDeExecucao(f"Ferramenta {FERRAMENTA} ausente no tools/list do servidor MCP.")
        _valida_argumentos(schema, args)
        politica = await _mcp(self.cliente.ler_politica(self._tp(trace)))
        contexto = {"args": args, "versao": _versao_politica(politica), "trace": trace,
                    "trace_do_cliente": cabecalho is not None}
        resultado = await _mcp(self.cliente.chamar(FERRAMENTA, args, self._tp(trace)))
        await self._tratar(up, task_id, resultado, contexto)

    async def _continuar(self, up, task_id, texto, pausa):
        escolha = valor_escolha(texto)
        if escolha == "recusar":
            resultado = await _mcp(self.cliente.chamar(
                FERRAMENTA, pausa["args"], self._tp(pausa["trace"]),
                input_responses={pausa["chave"]: {"action": "decline"}}, request_state=pausa["state"]))
            if resultado.is_error or (resultado.structured_content or {}).get("reservado") is not False:
                texto_erro = resultado.content[0].text if resultado.content else "Resposta inesperada na recusa."
                raise FalhaDeExecucao(texto_erro)
            await up.cancel()
            return
        if escolha not in pausa["alts"]:
            await self._pausar(up, task_id, pausa)
            return
        resultado = await _mcp(self.cliente.chamar(
            FERRAMENTA, pausa["args"], self._tp(pausa["trace"]),
            input_responses={pausa["chave"]: {"action": "accept", "content": {"sala": escolha}}},
            request_state=pausa["state"]))
        await self._tratar(up, task_id, resultado, pausa)

    async def _tratar(self, up, task_id, resultado, contexto):
        if isinstance(resultado, InputRequiredResult):
            alternativas = _alternativas(resultado.input_requests)
            pausa = {**contexto, "state": resultado.request_state, "alts": alternativas,
                     "chave": next(iter(resultado.input_requests))}
            await self._pausar(up, task_id, pausa)
            return
        if resultado.is_error:
            texto = resultado.content[0].text if resultado.content else "Erro na tool"
            raise FalhaDeExecucao(texto)
        dados = resultado.structured_content or {}
        if dados.get("reservado") is False:
            await up.cancel()
            return
        # Conteúdo do artifact: a reserva criada mais `politica`, como em exemplos/wire/10 e no enunciado (L316 a L327).
        reserva = {campo: dados[campo] for campo in ("reserva", "sala", "inicio", "fim", "responsavel")}
        reserva["politica"] = contexto["versao"]
        await up.add_artifact(parts=[Part(text=json.dumps(reserva, ensure_ascii=False))], name="reserva")
        confirmacao = up.new_agent_message([Part(text=f"Reserva {reserva['reserva']} confirmada na {reserva['sala']}.")])
        await self._com_mensagem_no_history(up, confirmacao)
        await up.complete(message=confirmacao)

    async def _pausar(self, up, task_id, pausa):
        self.pendencias[task_id] = pausa
        mensagem = up.new_agent_message([Part(text="alternativas: " + ", ".join(pausa["alts"]))])
        await self._com_mensagem_no_history(up, mensagem)
        await up.requires_input(message=mensagem)

    async def _com_mensagem_no_history(self, up, mensagem):
        """Publica a mensagem em `WORKING` antes do estado final: o SDK a move para o `history` quando o estado seguinte chega.

        O estado seguinte repete a mesma mensagem em `status.message` (como em `exemplos/wire/08` a `10`). O task store
        (`armazenamento.py`) mantém cada `messageId` uma só vez no `history`.
        """
        await up.update_status(pb.TASK_STATE_WORKING, message=mensagem)

    async def _falhar(self, up, texto):
        mensagem = up.new_agent_message([Part(text=texto)])
        await self._com_mensagem_no_history(up, mensagem)
        await up.failed(message=mensagem)
