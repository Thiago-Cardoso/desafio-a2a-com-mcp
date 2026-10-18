"""G-01: validação de MCP-Protocol-Version no transporte (enunciado L197; spec MUST)."""
import asyncio
import json

import pytest

from servidor_salas.middleware import ExigeVersaoProtocolo

META = "io.modelcontextprotocol/protocolVersion"


def corpo(versao_meta=None, metodo="tools/call"):
    params = {"name": "listar_salas", "arguments": {}}
    if versao_meta is not None:
        params["_meta"] = {META: versao_meta, "io.modelcontextprotocol/clientCapabilities": {}}
    return json.dumps({"jsonrpc": "2.0", "id": 7, "method": metodo, "params": params}).encode()


def executa(headers, body, path="/mcp", method="POST"):
    """Roda o middleware contra um app falso. Devolve (status, json_do_erro_ou_None, corpo_recebido_pelo_app)."""
    recebido = {}
    enviado = []

    async def app(scope, receive, send):
        recebido["corpo"] = (await receive())["body"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive_cliente():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        enviado.append(msg)

    scope = {"type": "http", "method": method, "path": path, "headers": headers}

    async def principal():
        mw = ExigeVersaoProtocolo(app)
        await asyncio.wait_for(mw(scope, receive_cliente, send), timeout=2)

    asyncio.run(principal())
    status = next((m["status"] for m in enviado if m["type"] == "http.response.start"), None)
    if status == 400:
        return status, json.loads(next(m["body"] for m in enviado if m["type"] == "http.response.body")), None
    return status, None, recebido.get("corpo")


def h(versao):
    headers = [(b"content-type", b"application/json")]
    if versao is not None:
        headers.append((b"mcp-protocol-version", versao.encode()))
    return headers


def test_header_legado_com_meta_2026_recebe_32020_e_400():
    # X-05 / V-02 / V-03 da auditoria: divergência não pode chegar ao caminho legado do SDK.
    status, erro, _ = executa(h("2025-11-25"), corpo("2026-07-28"))
    assert status == 400
    assert erro["error"]["code"] == -32020
    assert "diverge" in erro["error"]["message"]


def test_header_2026_com_meta_2026_passa_e_corpo_chega_intacto():
    status, erro, recebido = executa(h("2026-07-28"), corpo("2026-07-28"))
    assert status == 200 and erro is None
    assert recebido == corpo("2026-07-28")


def test_header_ausente_recebe_32020():
    status, erro, _ = executa(h(None), corpo("2026-07-28"))
    assert status == 400 and erro["error"]["code"] == -32020


def test_header_legado_sem_meta_recebe_32020():
    # Sem _meta de versão, o header legado ainda é versão não suportada por este servidor.
    status, erro, _ = executa(h("2025-11-25"), corpo(None))
    assert status == 400 and erro["error"]["code"] == -32020


def test_header_2026_sem_meta_de_versao_segue_para_o_sdk():
    # Sem _meta de versão, a rejeição -32602 é do SDK (teste de regressão em test_regressao).
    status, erro, _ = executa(h("2026-07-28"), corpo(None))
    assert status == 200 and erro is None


def test_meta_versao_nao_suportada_recebe_32020_mesmo_com_header_igual():
    status, erro, _ = executa(h("2025-11-25"), corpo("2025-11-25"))
    assert status == 400 and erro["error"]["code"] == -32020


def test_json_invalido_segue_para_o_sdk():
    status, erro, _ = executa(h("2026-07-28"), b"{nao e json")
    assert status == 200 and erro is None


def test_get_nao_e_validado():
    status, erro, _ = executa([], b"", method="GET")
    assert status == 200 and erro is None
