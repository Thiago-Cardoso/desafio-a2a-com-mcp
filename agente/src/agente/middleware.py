"""Middlewares ASGI do endpoint A2A: validação de formato e compatibilidade de versão."""
import json
import sys

from starlette.responses import JSONResponse

from .pedido import MSG_FORMATO, escolha_valida, pedido_valido


def _texto_mensagem(mensagem: dict):
    """Texto das partes, ou None se a estrutura não for a do contrato (parts lista de objetos com `text` string)."""
    partes = mensagem.get("parts", [])
    if not isinstance(partes, list):
        return None
    textos = []
    for parte in partes:
        if not isinstance(parte, dict) or not isinstance(parte.get("text", ""), str):
            return None
        textos.append(parte.get("text", ""))
    return "".join(textos)


class ValidaFormato:
    """Erro de validação (-32602) antes de qualquer Task ser criada (Q-03)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/a2a":
            return await self.app(scope, receive, send)
        corpo = b""
        mais = True
        while mais:
            mensagem = await receive()
            corpo += mensagem.get("body", b"")
            mais = mensagem.get("more_body", False)
        erro = _erro_formato(corpo)
        if erro is not None:
            resposta = JSONResponse(erro, status_code=200)
            return await resposta(scope, receive, send)

        async def reproduzir():
            return {"type": "http.request", "body": corpo, "more_body": False}

        return await self.app(scope, reproduzir, send)


def _erro_formato(corpo: bytes):
    try:
        dados = json.loads(corpo)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(dados, dict) or dados.get("method") != "SendMessage":
        return None
    params = dados.get("params")
    mensagem = params.get("message") if isinstance(params, dict) else None
    if not isinstance(mensagem, dict):
        return None   # estrutura fora do contrato: o SDK A2A responde com o seu erro de protocolo
    texto = _texto_mensagem(mensagem)
    if texto is None:
        return None
    if mensagem.get("taskId"):
        ok = escolha_valida(texto)
    else:
        ok = pedido_valido(texto)
    if ok:
        return None
    return {"jsonrpc": "2.0", "id": dados.get("id"),
            "error": {"code": -32602, "message": MSG_FORMATO}}


class CompatibilidadeVersao:
    """Desvio controlado de §3.6.2 (MUST): cabeçalho A2A-Version ausente vira 1.0 neste endpoint."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/a2a":
            cabecalhos = list(scope["headers"])
            if not any(k.lower() == b"a2a-version" for k, _ in cabecalhos):
                scope["headers"] = cabecalhos + [(b"a2a-version", b"1.0")]
                print(json.dumps({"aviso": "A2A-Version ausente; tratado como 1.0 (desvio de §3.6.2)"}),
                      file=sys.stderr, flush=True)
        await self.app(scope, receive, send)
