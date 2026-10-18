"""Cliente MCP do agente: um cliente vivo por processo (ids JSON-RPC monotônicos), chamadas cruas.

A capability de elicitação anunciada é exatamente `{"form": {}}` (enunciado L196), por um `Transport` próprio.

O `input_required` volta para a ponte, sem laço automático de elicitação. O `traceparent`
da Task vai em `_meta` de todo request feito em nome dela (RF-38).
"""
from __future__ import annotations

import asyncio
import dataclasses
import re
from typing import Any

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import PaginatedRequestParams

VERSAO_PROTOCOLO = "2026-07-28"  # revisão do enunciado (L102); o servidor aceita só esta

_CABECALHO_TP = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


async def _sem_resposta_automatica(context, params):
    # O agente não responde elicitações sozinho. Se este callback rodar, o laço automático foi acionado.
    raise RuntimeError("elicitação respondida automaticamente: o agente deve ver o input_required cru")


CHAVE_CAPACIDADES = "io.modelcontextprotocol/clientCapabilities"


def capacidades_so_form(mensagem):
    """Devolve a mensagem sem `url` na capability de elicitation: `{"elicitation": {"form": {}}}` (enunciado L196).

    O SDK `mcp` 2.3.0 anuncia `form` e `url` sempre que há `elicitation_callback`, e não tem parâmetro público para
    restringir. Esta função age sobre a mensagem JSON-RPC já montada, só remove a chave `url` e preserva todo o resto.
    Nunca altera o original: o SDK reutiliza o mesmo dicionário de capabilities em todos os requests.
    """
    params = getattr(mensagem, "params", None)
    meta = params.get("_meta") if isinstance(params, dict) else None
    capacidades = meta.get(CHAVE_CAPACIDADES) if isinstance(meta, dict) else None
    elicitacao = capacidades.get("elicitation") if isinstance(capacidades, dict) else None
    if not isinstance(elicitacao, dict) or "url" not in elicitacao:
        return mensagem
    nova_elicitacao = {chave: valor for chave, valor in elicitacao.items() if chave != "url"}
    novo_meta = {**meta, CHAVE_CAPACIDADES: {**capacidades, "elicitation": nova_elicitacao}}
    return mensagem.model_copy(update={"params": {**params, "_meta": novo_meta}})


class _EscritaSoForm:
    """Decora o `WriteStream` (protocolo público do SDK): cada mensagem enviada passa por `capacidades_so_form`."""

    def __init__(self, interna):
        self._interna = interna

    async def send(self, item, /):
        nova = capacidades_so_form(item.message)
        if nova is not item.message:
            item = dataclasses.replace(item, message=nova)
        await self._interna.send(item)

    async def aclose(self):
        await self._interna.aclose()

    async def __aenter__(self):
        await self._interna.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._interna.__aexit__(*exc)


class TransporteSoForm:
    """`Transport` (protocolo público do SDK): o transporte Streamable HTTP do SDK, com a capability só em `form`."""

    def __init__(self, url: str):
        self._interno = streamable_http_client(url)

    async def __aenter__(self):
        leitura, escrita = await self._interno.__aenter__()
        return leitura, _EscritaSoForm(escrita)

    async def __aexit__(self, *exc):
        return await self._interno.__aexit__(*exc)


class ClienteMcp:
    """Uma sessão MCP por processo, aberta na primeira chamada. Não guarda estado de protocolo entre Tasks."""

    def __init__(self, url: str):
        self.url = url
        self._cliente: Client | None = None
        self._abertura = asyncio.Lock()

    async def _sessao(self):
        if self._cliente is None:
            async with self._abertura:
                if self._cliente is None:
                    # `mode` com a versão do protocolo fixa a revisão sem sondar `server/discover`: todo request MCP
                    # do agente passa a ser feito em nome de uma Task e leva o traceparent dela (enunciado L198).
                    cliente = Client(TransporteSoForm(self.url), mode=VERSAO_PROTOCOLO, elicitation_callback=_sem_resposta_automatica)
                    await cliente.__aenter__()
                    self._cliente = cliente
        return self._cliente.session

    async def listar_ferramentas(self, traceparent: str) -> dict[str, Any]:
        """tools/list: nome -> inputSchema. Feito antes de cada pedido novo (RF-34)."""
        sessao = await self._sessao()
        resposta = await sessao.list_tools(params=PaginatedRequestParams(meta={"traceparent": traceparent}))
        return {ferramenta.name: ferramenta.input_schema for ferramenta in resposta.tools}

    async def ler_politica(self, traceparent: str) -> str:
        """resources/read de `politica://uso` (RF-35). Devolve o texto integral."""
        sessao = await self._sessao()
        resposta = await sessao.read_resource("politica://uso", meta={"traceparent": traceparent})
        return resposta.contents[0].text

    async def chamar(self, nome: str, argumentos: dict, traceparent: str,
                     input_responses: dict | None = None, request_state: str | None = None) -> Any:
        sessao = await self._sessao()
        return await sessao.call_tool(
            nome, argumentos,
            input_responses=input_responses, request_state=request_state,
            meta={"traceparent": traceparent}, allow_input_required=True)


def traceparent_para(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


def valido(traceparent: str) -> bool:
    return bool(_CABECALHO_TP.match(traceparent))
