"""Servidor MCP das salas: tools, resource e MRTR. Regras de negócio ficam em `dominio`."""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.request_state import RequestStateSecurity
from mcp.shared.exceptions import MCPError
from mcp_types import InputRequiredResult
from mcp_types.jsonrpc import INVALID_PARAMS, MISSING_REQUIRED_CLIENT_CAPABILITY

from . import mrtr
from .dominio import MSG_SEM_ALTERNATIVAS, Dominio, ErroNegocio, ParametroInvalido, _data
from .middleware import LogRequisicoes
from .saidas import ConflitoOut, Disponibilidade, ListaDeSalas, ReservaOut, SalaOut

MCP_NOME = "central-de-salas"  # nome e versão como em exemplos/wire (serverInfo)
MCP_VERSAO = "1.0.0"


def _campo(obj: Any, nome: str) -> Any:
    return obj.get(nome) if isinstance(obj, dict) else getattr(obj, nome, None)


def _data_invalida(exc: ParametroInvalido) -> MCPError:
    return MCPError(code=INVALID_PARAMS, message=str(exc))


def _exige_form(ctx: Context) -> None:
    """Elicitation só para cliente que declarou form mode (RF-31). Vale para todo caminho que devolve `input_required`."""
    caps = ctx.client_capabilities
    if caps and caps.elicitation and caps.elicitation.form is not None:
        return
    raise MCPError(code=MISSING_REQUIRED_CLIENT_CAPABILITY,
                   message="Client did not declare the form elicitation capability",
                   data={"requiredCapabilities": {"elicitation": {"form": {}}}})


def criar_servidor(dominio: Dominio, segredo: bytes) -> MCPServer:
    mcp = MCPServer(
        MCP_NOME,
        version=MCP_VERSAO,
        request_state_security=RequestStateSecurity(keys=[segredo], ttl=900),
        middleware=[LogRequisicoes()],
    )

    @mcp.tool(name="listar_salas", description='Lista todas as salas com capacidade e recursos.', structured_output=True)
    def listar_salas() -> ListaDeSalas:
        return ListaDeSalas(salas=[SalaOut(**sala) for sala in dominio.salas_lista()])

    @mcp.tool(name="consultar_disponibilidade", description='Diz se uma sala esta livre no intervalo, e quais reservas conflitam.', structured_output=True)
    def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
        try:
            _, ini, fi = dominio.validar(sala, inicio, fim)
        except ErroNegocio as erro:
            raise ToolError(erro.mensagem) from erro
        except ParametroInvalido as erro:
            raise _data_invalida(erro) from erro
        conflitos = dominio.conflitos(sala, ini, fi)
        return Disponibilidade(
            sala=sala, livre=not conflitos,
            conflitos=[ConflitoOut(id=r.id, inicio=r.inicio.isoformat(), fim=r.fim.isoformat(), responsavel=r.responsavel)
                       for r in conflitos])

    @mcp.tool(name="reservar_sala", description='Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar.', structured_output=True)
    def reservar_sala(sala: str, inicio: str, fim: str, responsavel: str,
                      ctx: Context) -> ReservaOut | InputRequiredResult:
        try:
            _, ini, fi = dominio.validar(sala, inicio, fim)
        except ErroNegocio as erro:
            raise ToolError(erro.mensagem) from erro
        except ParametroInvalido as erro:
            raise _data_invalida(erro) from erro

        if ctx.input_responses is None:
            if not dominio.conflitos(sala, ini, fi):
                return _concluida(dominio, dominio.reservar(sala, ini, fi, responsavel))
            alternativas = dominio.alternativas(dominio.salas[sala], ini, fi)
            if not alternativas:
                raise ToolError(MSG_SEM_ALTERNATIVAS)
            _exige_form(ctx)
            return InputRequiredResult(
                inputRequests=mrtr.requisicao_escolha(alternativas),
                requestState=mrtr.selar(sala, inicio, fim, responsavel, alternativas),
            )

        # Retry: o SDK já verificou a integridade do requestState e a igualdade dos argumentos.
        if ctx.request_state is None:
            raise MCPError(code=INVALID_PARAMS, message="Invalid or expired requestState")
        estado = mrtr.abrir(ctx.request_state)
        resposta = ctx.input_responses.get(mrtr.CHAVE_ESCOLHA)
        if resposta is None:
            return _nova_escolha(dominio, estado, ctx)
        acao = _campo(resposta, "action")
        if acao in ("decline", "cancel"):
            return ReservaOut(reservado=False, motivo="recusado")
        conteudo = _campo(resposta, "content") or {}
        escolhida = _campo(conteudo, "sala")
        if escolhida not in estado["alternativas"]:
            return _nova_escolha(dominio, estado, ctx)
        ini2 = _data(estado["inicio"])
        fim2 = _data(estado["fim"])
        if dominio.conflitos(escolhida, ini2, fim2):
            return _nova_escolha(dominio, estado, ctx)
        return _concluida(dominio, dominio.reservar(escolhida, ini2, fim2, estado["responsavel"]))

    @mcp.resource("politica://uso", mime_type="text/markdown")
    def politica_uso() -> str:
        return dominio.politica_texto

    return mcp


def _concluida(dominio: Dominio, reserva) -> ReservaOut:
    return ReservaOut(reservado=True, reserva=reserva.id, sala=reserva.sala,
                     inicio=reserva.inicio.isoformat(), fim=reserva.fim.isoformat(),
                     responsavel=reserva.responsavel, politica=dominio.versao_politica)


def _nova_escolha(dominio: Dominio, estado: dict, ctx: Context) -> InputRequiredResult:
    ini, fi = _data(estado["inicio"]), _data(estado["fim"])
    alternativas = dominio.alternativas(dominio.salas[estado["sala"]], ini, fi)
    if not alternativas:
        raise ToolError(MSG_SEM_ALTERNATIVAS)
    _exige_form(ctx)
    return InputRequiredResult(
        inputRequests=mrtr.requisicao_escolha(alternativas),
        requestState=mrtr.selar(estado["sala"], estado["inicio"], estado["fim"], estado["responsavel"], alternativas),
    )
