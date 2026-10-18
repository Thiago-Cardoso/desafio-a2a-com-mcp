"""Mensagem para Task terminal: o -32004 continua o mesmo e o caminho de erro do SDK (que vaza tarefas) não é percorrido."""
import asyncio
import gc
import logging

import pytest
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import a2a_pb2
from a2a.utils.errors import UnsupportedOperationError

from agente.a2a_app import _card
from agente.armazenamento import TaskStoreSemRepeticoes
from agente.manipulador import ManipuladorRecusaTerminal

TERMINAIS = [a2a_pb2.TASK_STATE_COMPLETED, a2a_pb2.TASK_STATE_FAILED, a2a_pb2.TASK_STATE_CANCELED, a2a_pb2.TASK_STATE_REJECTED]


class ExecutorNaoDeveRodar:
    async def execute(self, contexto, fila):
        raise AssertionError("o executor não deveria ser chamado")

    async def cancel(self, contexto, fila):
        raise AssertionError("o executor não deveria ser chamado")


def pedido(task_id="", texto="escolha=recusar"):
    return a2a_pb2.SendMessageRequest(message=a2a_pb2.Message(
        message_id="m-1", role=a2a_pb2.ROLE_USER, task_id=task_id, parts=[a2a_pb2.Part(text=texto)]))


async def com_tarefa(estado, classe=ManipuladorRecusaTerminal):
    loja = TaskStoreSemRepeticoes()
    ctx = ServerCallContext()
    await loja.save(a2a_pb2.Task(id="t-1", context_id="c-1", status=a2a_pb2.TaskStatus(state=estado)), ctx)
    return classe(agent_executor=ExecutorNaoDeveRodar(), task_store=loja, agent_card=_card()), ctx


def tarefas_pendentes():
    return {t for t in asyncio.all_tasks() if not t.done()} - {asyncio.current_task()}


@pytest.mark.parametrize("estado", TERMINAIS)
def test_terminal_devolve_o_mesmo_erro_do_sdk_sem_tarefas_pendentes(estado, caplog):
    async def cenario():
        antes = tarefas_pendentes()
        manipulador, ctx = await com_tarefa(estado)
        with pytest.raises(UnsupportedOperationError) as erro:
            await manipulador.on_message_send(pedido("t-1"), ctx)
        assert str(erro.value.message) == f"Task t-1 is in terminal state: {a2a_pb2.TaskState.Name(estado)}"
        with pytest.raises(UnsupportedOperationError):
            async for _ in manipulador.on_message_send_stream(pedido("t-1"), ctx):
                pass
        gc.collect()
        await asyncio.sleep(0.05)
        assert tarefas_pendentes() == antes   # nenhum _dispatch_loop deixado para trás

    with caplog.at_level(logging.DEBUG):
        asyncio.run(cenario())
        gc.collect()
    ruim = [r.getMessage() for r in caplog.records
            if "Failed to detach" in r.getMessage() or "was destroyed but it is pending" in r.getMessage()]
    assert ruim == []


def test_sem_task_id_inexistente_e_nao_terminal_nao_sao_interceptados():
    async def cenario():
        manipulador, ctx = await com_tarefa(a2a_pb2.TASK_STATE_INPUT_REQUIRED)
        assert await manipulador._recusar_se_terminal(pedido(""), ctx) is None            # sem taskId
        assert await manipulador._recusar_se_terminal(pedido("nao-existe"), ctx) is None  # inexistente: o SDK decide
        assert await manipulador._recusar_se_terminal(pedido("t-1"), ctx) is None         # pausada, não terminal

    asyncio.run(cenario())


def test_contraste_o_handler_do_sdk_ainda_deixa_tarefas_pendentes():
    """Documenta o defeito do a2a-sdk 1.2.2 que a mitigação evita. Se este teste falhar, o SDK foi corrigido e a mitigação pode sair."""
    async def cenario():
        antes = tarefas_pendentes()
        manipulador, ctx = await com_tarefa(a2a_pb2.TASK_STATE_COMPLETED, classe=DefaultRequestHandler)
        with pytest.raises(UnsupportedOperationError):
            await manipulador.on_message_send(pedido("t-1"), ctx)
        await asyncio.sleep(0.05)
        return tarefas_pendentes() - antes

    pendentes = asyncio.run(cenario())
    assert any("_dispatch_loop" in repr(t) for t in pendentes)
