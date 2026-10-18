"""F-04: corpos JSON-RPC malformados em /mcp não geram HTTP 500, e a requisição válida continua funcionando."""
import json
import secrets
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from servidor_salas.dominio import Dominio
from servidor_salas.middleware import ExigeVersaoProtocolo
from servidor_salas.server import criar_servidor

RAIZ = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (RAIZ / "dados").exists(), reason="dados/ ausente (fora do repositório do desafio)")
PROTO = "2026-07-28"
CAPS = {"elicitation": {"form": {}}}


def requisicao(params):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


def chamada(**extra):
    return {"name": "listar_salas", "arguments": {}, **extra}


@pytest.fixture(scope="module")
def cliente():
    servidor = criar_servidor(Dominio(RAIZ / "dados"), secrets.token_hex(32).encode())
    with TestClient(ExigeVersaoProtocolo(servidor.streamable_http_app(stateless_http=True)),
                    base_url="http://127.0.0.1:7301", raise_server_exceptions=False) as c:
        yield c


def post(c, corpo):
    cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTO,
           "Mcp-Method": "tools/call", "Mcp-Name": "listar_salas"}
    return c.post("/mcp", content=corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode(), headers=cab)


MALFORMADOS = [
    b"",
    b"{",
    b"nao e json",
    b"[]",
    b"{}",
    b"5",
    requisicao([]),
    requisicao("x"),
    requisicao(chamada(_meta="x")),
    requisicao(chamada(_meta=[])),
    requisicao(chamada(_meta=5)),
    requisicao(chamada(_meta={"io.modelcontextprotocol/protocolVersion": PROTO, "io.modelcontextprotocol/clientCapabilities": "x"})),
]


@pytest.mark.parametrize("corpo", MALFORMADOS, ids=lambda c: (c if isinstance(c, bytes) else json.dumps(c))[:60])
def test_sem_500_e_com_erro_jsonrpc(cliente, corpo):
    r = post(cliente, corpo)
    assert r.status_code != 500 and "Traceback" not in r.text
    erro = r.json()["error"]
    assert erro["code"] in (-32700, -32600, -32602, -32020, -32021) and erro["message"]


def test_requisicao_valida_continua_funcionando(cliente):
    meta = {"io.modelcontextprotocol/protocolVersion": PROTO, "io.modelcontextprotocol/clientCapabilities": CAPS}
    r = post(cliente, requisicao(chamada(_meta=meta)))
    assert r.status_code == 200
    resultado = r.json()["result"]
    assert not resultado.get("isError") and len(resultado["structuredContent"]["salas"]) >= 1


def test_meta_fora_do_contrato_e_erro_de_parametro_do_sdk(cliente):
    r = post(cliente, requisicao(chamada(_meta="x")))
    assert r.status_code == 400 and r.json()["error"]["code"] == -32602
