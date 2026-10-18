"""Observação e validação de transporte."""
import asyncio
import json
import sys
from datetime import datetime, timezone

from starlette.responses import JSONResponse


class LogRequisicoes:
    """Middleware de contexto do SDK: uma linha JSON em stderr por request."""

    async def __call__(self, ctx, call_next):
        meta = (ctx.params or {}).get("_meta", {}) if isinstance(ctx.params, dict) else {}
        registro = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "metodo": ctx.method,
            "id": ctx.request_id,
            "traceparent": meta.get("traceparent"),
        }
        if ctx.method == "tools/call" and isinstance(ctx.params, dict):
            registro["tool"] = ctx.params.get("name")
        print(json.dumps(registro, ensure_ascii=False), file=sys.stderr, flush=True)
        return await call_next(ctx)


VERSAO_SUPORTADA = "2026-07-28"
META_VERSAO = "io.modelcontextprotocol/protocolVersion"


def _erro_versao(cabecalhos, corpo: bytes):
    """Devolve o corpo do erro -32020 quando o transporte recusa a versão, ou None para seguir.

    Regras (enunciado L197; spec MUST): o header `MCP-Protocol-Version` é obrigatório e precisa
    coincidir com `_meta.io.modelcontextprotocol/protocolVersion` do corpo. Vale para qualquer POST em /mcp,
    antes do roteamento do SDK (que trata headers legados em outro caminho) e antes das regras de tool
    (`-32021`, `-32602`): a versão divergente tem precedência.
    """
    header = next((v.decode("latin-1") for k, v in cabecalhos if k.lower() == b"mcp-protocol-version"), None)
    try:
        dados = json.loads(corpo)
    except (ValueError, UnicodeDecodeError):
        dados = None
    id_ = dados.get("id") if isinstance(dados, dict) else None
    if header is None:
        return _corpo_erro(id_, "MCP-Protocol-Version ausente")
    if not isinstance(dados, dict):
        return None  # JSON inválido ou lote: o SDK responde com o erro de protocolo adequado
    params = dados.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(meta, dict):
        meta = {}   # `_meta` ausente ou fora do contrato: a regra de -32602 do SDK decide
    versao_corpo = meta.get(META_VERSAO)
    if versao_corpo is None:
        if header != VERSAO_SUPORTADA:
            return _corpo_erro(id_, f"MCP-Protocol-Version {header!r} não suportada; use {VERSAO_SUPORTADA}")
        return None  # sem _meta de versão: a regra de -32602 do SDK decide
    if header != versao_corpo:
        return _corpo_erro(id_, f"MCP-Protocol-Version {header!r} diverge de _meta ({versao_corpo!r})")
    if versao_corpo != VERSAO_SUPORTADA:
        return _corpo_erro(id_, f"versão {versao_corpo!r} não suportada; use {VERSAO_SUPORTADA}")
    return None


def _corpo_erro(id_, mensagem):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32020, "message": mensagem}}


class ExigeVersaoProtocolo:
    """ASGI: POST em /mcp com versão ausente, divergente do _meta ou não suportada recebe HTTP 400 e -32020."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/mcp":
            return await self.app(scope, receive, send)
        corpo = b""
        mais = True
        while mais:
            mensagem = await receive()
            corpo += mensagem.get("body", b"")
            mais = mensagem.get("more_body", False)
        erro = _erro_versao(scope["headers"], corpo)
        if erro is not None:
            resposta = JSONResponse(erro, status_code=400)
            return await resposta(scope, receive, send)

        entregue = False

        async def reproduzir():
            # Corpo uma vez; depois, nada de desconexão: o SDK usa receive para ouvir o cliente
            # enquanto responde, e um http.disconnect precoce cancelaria a resposta.
            nonlocal entregue
            if not entregue:
                entregue = True
                return {"type": "http.request", "body": corpo, "more_body": False}
            await asyncio.Event().wait()

        return await self.app(scope, reproduzir, send)
