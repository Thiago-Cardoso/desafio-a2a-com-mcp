"""RF-36 (enunciado L196): o agente anuncia, no fio, exatamente `{"elicitation": {"form": {}}}`.

Estratégia: um `Transport` próprio, só com protocolos públicos do SDK (`mcp.client.Transport`, `WriteStream`), remove `url` da
capability das mensagens já montadas. A prova é a mensagem REAL recebida por um servidor MCP de verdade (o do projeto),
registrada por um ASGI que só observa e repassa o request.

- Testes unitários: a função pura e o decorador de escrita (preservam tudo, não mutam o original do SDK).
- Teste no fio: o fluxo completo (descoberta, leitura do recurso, pausa por elicitation, recusa) com a capability exata.
- Contraste: o `Client` puro do SDK anuncia `form` e `url`. Se este teste falhar um dia, o SDK ganhou controle público e o
  transporte próprio pode ser removido.
"""
import asyncio
import copy
import dataclasses
import json
import secrets
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from mcp import Client
from mcp_types import JSONRPCRequest

from agente.mcp_cliente import CHAVE_CAPACIDADES, ClienteMcp, TransporteSoForm, _EscritaSoForm, _sem_resposta_automatica, capacidades_so_form

RAIZ = Path(__file__).resolve().parents[2]
SRC_SERVIDOR = RAIZ / "servidor-mcp" / "src"
EXATA = {"elicitation": {"form": {}}}
TP = "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"


def requisicao(caps, extra_meta=None):
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", CHAVE_CAPACIDADES: caps, **(extra_meta or {})}
    return JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/call",
                          params={"name": "reservar_sala", "arguments": {"sala": "s"}, "_meta": meta})


# ---------------------------------------------------------------- unitários
def test_remove_somente_url_e_preserva_todo_o_resto():
    original = requisicao({"elicitation": {"form": {}, "url": {}}, "sampling": {}}, {"traceparent": TP})
    nova = capacidades_so_form(original)
    assert nova.params["_meta"][CHAVE_CAPACIDADES] == {"elicitation": {"form": {}}, "sampling": {}}
    assert nova.params["_meta"]["traceparent"] == TP
    assert nova.params["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    assert nova.params["name"] == "reservar_sala" and nova.params["arguments"] == {"sala": "s"}
    assert (nova.id, nova.method, nova.jsonrpc) == (7, "tools/call", "2.0")


def test_nao_altera_o_original_porque_o_sdk_reutiliza_o_mesmo_dicionario():
    caps = {"elicitation": {"form": {}, "url": {}}}
    original = requisicao(caps)
    antes = copy.deepcopy(original.params)
    capacidades_so_form(original)
    assert original.params == antes and caps == {"elicitation": {"form": {}, "url": {}}}


def test_devolve_a_mesma_mensagem_quando_nao_ha_o_que_remover():
    assert capacidades_so_form(requisicao(EXATA)) is not None
    m = requisicao(EXATA)
    assert capacidades_so_form(m) is m
    sem_meta = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list", params={})
    assert capacidades_so_form(sem_meta) is sem_meta
    sem_params = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    assert capacidades_so_form(sem_params) is sem_params
    sem_elicitacao = requisicao({"sampling": {}})
    assert capacidades_so_form(sem_elicitacao) is sem_elicitacao


def test_decorador_de_escrita_envia_a_versao_corrigida_e_preserva_os_metadados():
    from mcp.shared.message import SessionMessage

    enviados = []

    class Interna:
        async def send(self, item, /):
            enviados.append(item)

        async def aclose(self):
            pass

    caps_compartilhadas = {"elicitation": {"form": {}, "url": {}}}
    escrita = _EscritaSoForm(Interna())
    item = SessionMessage(message=requisicao(caps_compartilhadas), metadata=None)
    asyncio.run(escrita.send(item))
    asyncio.run(escrita.send(SessionMessage(message=requisicao(caps_compartilhadas), metadata=None)))
    assert [i.message.params["_meta"][CHAVE_CAPACIDADES] for i in enviados] == [EXATA, EXATA]
    assert caps_compartilhadas == {"elicitation": {"form": {}, "url": {}}}  # o dicionário do SDK não foi mutado
    assert dataclasses.replace(enviados[0], message=item.message).metadata == item.metadata


# ---------------------------------------------------------------- no fio
@pytest.fixture(scope="module")
def servidor_com_captura():
    if not (SRC_SERVIDOR / "servidor_salas").exists():
        pytest.skip("servidor-mcp ausente (fora do repositório do desafio)")
    sys.path.insert(0, str(SRC_SERVIDOR))
    from servidor_salas.dominio import Dominio
    from servidor_salas.middleware import ExigeVersaoProtocolo
    from servidor_salas.server import criar_servidor

    capturados = []

    class Captura:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["method"] == "POST":
                corpo, mais = b"", True
                while mais:
                    m = await receive()
                    corpo += m.get("body", b"")
                    mais = m.get("more_body", False)
                try:
                    capturados.append(json.loads(corpo))
                except ValueError:
                    pass
                entregue = False

                async def repete():
                    nonlocal entregue
                    if not entregue:
                        entregue = True
                        return {"type": "http.request", "body": corpo, "more_body": False}
                    await asyncio.Event().wait()

                return await self.app(scope, repete, send)
            await self.app(scope, receive, send)

    servidor = criar_servidor(Dominio(RAIZ / "dados"), secrets.token_hex(32).encode())
    app = Captura(ExigeVersaoProtocolo(servidor.streamable_http_app(stateless_http=True)))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    uv = uvicorn.Server(config)
    threading.Thread(target=uv.run, daemon=True).start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    porta = uv.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{porta}/mcp", capturados
    uv.should_exit = True


ARGS = {"sala": "sala-garagem", "inicio": "2026-11-03T14:00:00-03:00", "fim": "2026-11-03T15:00:00-03:00", "responsavel": "Fio"}


def test_fluxo_completo_anuncia_exatamente_form_no_fio(servidor_com_captura):
    url, capturados = servidor_com_captura
    capturados.clear()

    async def fluxo():
        cliente = ClienteMcp(url)
        ferramentas = await cliente.listar_ferramentas(TP)
        politica = await cliente.ler_politica(TP)
        pausa = await cliente.chamar("reservar_sala", ARGS, TP)                       # conflito: input_required cru
        chave = next(iter(pausa.input_requests))
        recusa = await cliente.chamar("reservar_sala", ARGS, TP, input_responses={chave: {"action": "decline"}},
                                      request_state=pausa.request_state)
        return ferramentas, politica, pausa, recusa

    ferramentas, politica, pausa, recusa = asyncio.run(fluxo())

    # a declaração exata, em TODOS os requests que chegaram ao servidor
    assert [c["method"] for c in capturados] == ["tools/list", "resources/read", "tools/call", "tools/call"]
    for c in capturados:
        assert c["params"]["_meta"][CHAVE_CAPACIDADES] == EXATA, c["method"]
        assert c["params"]["_meta"]["traceparent"] == TP                               # demais campos preservados
        assert c["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    assert len({c["id"] for c in capturados}) == 4                                       # ids únicos preservados
    # o fluxo de elicitation segue funcionando por inteiro
    assert "reservar_sala" in ferramentas and politica.startswith("versao: ")
    assert type(pausa).__name__ == "InputRequiredResult" and pausa.request_state
    assert recusa.structured_content["reservado"] is False


def test_contraste_o_client_puro_do_sdk_anuncia_form_e_url(servidor_com_captura):
    """Prova que o teste acima detecta a diferença: sem o transporte próprio, o SDK anuncia também `url`."""
    url, capturados = servidor_com_captura
    capturados.clear()

    async def fluxo():
        async with Client(url, mode="2026-07-28", elicitation_callback=_sem_resposta_automatica) as c:
            await c.session.list_tools()

    asyncio.run(fluxo())
    assert capturados and capturados[0]["params"]["_meta"][CHAVE_CAPACIDADES] == {"elicitation": {"form": {}, "url": {}}}


def test_o_transporte_proprio_usa_o_mesmo_endereco_e_nao_exige_api_privada():
    import inspect
    import agente.mcp_cliente as m

    codigo = inspect.getsource(m)
    for proibido in ("_build_capabilities", "_build_session", "_stamp", "_dispatcher", "monkeypatch", "setattr("):
        assert proibido not in codigo, proibido
    assert TransporteSoForm("http://127.0.0.1:1/mcp") is not None
