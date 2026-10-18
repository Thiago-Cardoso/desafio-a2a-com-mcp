"""F-04: corpos JSON-RPC malformados no endpoint A2A não geram HTTP 500; o fluxo válido segue intacto."""
import asyncio
import json

import pytest
from starlette.testclient import TestClient

from agente.a2a_app import criar_app
from agente.middleware import CompatibilidadeVersao, ValidaFormato

PEDIDO = "reservar sala=sala-a inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Ana"


def envia(texto_ou_obj):
    return texto_ou_obj if isinstance(texto_ou_obj, bytes) else json.dumps(texto_ou_obj).encode()


def send_message(params):
    return {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": params}


def mensagem(texto, **extra):
    return {"message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"text": texto}], **extra}}


def executa(corpo: bytes):
    """Roda só o middleware contra um app falso: devolve (resposta_do_middleware | None, corpo_entregue_ao_app | None)."""
    entregue, enviado = {}, []

    async def app(scope, receive, send):
        entregue["corpo"] = (await receive())["body"]

    async def receive():
        return {"type": "http.request", "body": corpo, "more_body": False}

    async def send(msg):
        enviado.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/a2a", "headers": []}
    asyncio.run(ValidaFormato(app)(scope, receive, send))
    resposta = next((json.loads(m["body"]) for m in enviado if m["type"] == "http.response.body"), None)
    return resposta, entregue.get("corpo")


MALFORMADOS = [
    b"",
    b"{",
    b"nao e json",
    b"[]",
    b"5",
    envia(send_message("x")),
    envia(send_message({"message": "x"})),
    envia(send_message({"message": {"parts": "x"}})),
    envia(send_message({"message": {"parts": [{"text": 5}]}})),
    envia(send_message({"message": {"parts": [5]}})),
    envia(send_message({"message": {"parts": [{"text": None}]}})),
]


@pytest.mark.parametrize("corpo", MALFORMADOS)
def test_middleware_nao_levanta_e_repassa_estrutura_fora_do_contrato_ao_sdk(corpo):
    resposta, entregue = executa(corpo)
    assert resposta is None and entregue == corpo   # o SDK A2A decide o erro de protocolo


@pytest.mark.parametrize("corpo", MALFORMADOS)
def test_http_sem_500_e_com_erro_jsonrpc(corpo):
    with TestClient(criar_app(), base_url="http://127.0.0.1:7300", raise_server_exceptions=False) as c:
        r = c.post("/a2a", content=corpo, headers={"Content-Type": "application/json", "A2A-Version": "1.0"})
    assert r.status_code != 500 and "Traceback" not in r.text
    erro = r.json()["error"]
    assert erro["code"] in (-32700, -32600, -32602) and erro["message"]


def test_pedido_fora_do_formato_continua_recusado_sem_task():
    resposta, entregue = executa(envia(send_message(mensagem("oi, quero reservar"))))
    assert entregue is None and resposta["error"]["code"] == -32602


def test_pedido_valido_e_escolha_continuam_chegando_ao_sdk():
    corpo = envia(send_message(mensagem(PEDIDO)))
    assert executa(corpo) == (None, corpo)
    escolha = envia(send_message(mensagem("escolha=recusar", taskId="t-1")))
    assert executa(escolha) == (None, escolha)


def test_escolha_invalida_com_task_continua_recusada():
    resposta, entregue = executa(envia(send_message(mensagem("sim", taskId="t-1"))))
    assert entregue is None and resposta["error"]["code"] == -32602


AVISO_VERSAO = {"aviso": "A2A-Version ausente; tratado como 1.0 (desvio de §3.6.2)"}


def executa_versao(cabecalhos, metodo="POST", caminho="/a2a"):
    """Roda só CompatibilidadeVersao contra um app falso: devolve os cabeçalhos que o app recebeu."""
    recebidos = {}

    async def app(scope, receive, send):
        recebidos["headers"] = scope["headers"]

    scope = {"type": "http", "method": metodo, "path": caminho, "headers": list(cabecalhos)}
    asyncio.run(CompatibilidadeVersao(app)(scope, None, None))
    return recebidos["headers"]


def avisos_de_compatibilidade(capsys):
    """Linhas JSON do aviso do middleware no stderr; ignora o log `Version mismatch` do SDK (logging, outro formato)."""
    return [json.loads(l) for l in capsys.readouterr().err.splitlines() if l.startswith("{") and "aviso" in l]


def versoes(cabecalhos):
    return [v for k, v in cabecalhos if k.lower() == b"a2a-version"]


def test_versao_ausente_insere_1_0_e_avisa_uma_vez(capsys):
    originais = [(b"content-type", b"application/json")]
    recebidos = executa_versao(originais)
    assert versoes(recebidos) == [b"1.0"]
    assert recebidos[:1] == originais   # os demais cabeçalhos seguem intactos
    assert avisos_de_compatibilidade(capsys) == [AVISO_VERSAO]


@pytest.mark.parametrize("valor", [b"1.0", b"0.3", b"", b"2.0"])
def test_versao_presente_e_preservada_sem_aviso(capsys, valor):
    originais = [(b"content-type", b"application/json"), (b"a2a-version", valor)]
    assert executa_versao(originais) == originais   # vazio e incompatível não equivalem a ausente
    assert avisos_de_compatibilidade(capsys) == []


@pytest.mark.parametrize("metodo,caminho", [("GET", "/a2a"), ("PUT", "/a2a"), ("POST", "/"), ("POST", "/a2a/x"),
                                            ("GET", "/.well-known/agent-card.json")])
def test_fora_do_escopo_nao_altera_cabecalhos_nem_avisa(capsys, metodo, caminho):
    originais = [(b"content-type", b"application/json")]
    assert executa_versao(originais, metodo, caminho) == originais
    assert avisos_de_compatibilidade(capsys) == []


def test_escopo_que_nao_e_http_passa_direto(capsys):
    chamado = []

    async def app(scope, receive, send):
        chamado.append(scope)

    scope = {"type": "lifespan"}
    asyncio.run(CompatibilidadeVersao(app)(scope, None, None))
    assert chamado == [scope] and avisos_de_compatibilidade(capsys) == []


@pytest.mark.parametrize("nome", [b"A2A-Version", b"a2a-version", b"A2a-VERSION"])
def test_nome_do_cabecalho_e_insensivel_a_caixa(capsys, nome):
    originais = [(nome, b"1.0")]
    assert executa_versao(originais) == originais
    assert avisos_de_compatibilidade(capsys) == []


def http_a2a(cabecalhos):
    """GetTask de Task inexistente: não toca o MCP, e `-32001` prova que o SDK aceitou a versão."""
    corpo = envia({"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "nao-existe"}})
    with TestClient(criar_app(), base_url="http://127.0.0.1:7300", raise_server_exceptions=False) as c:
        return c.post("/a2a", content=corpo, headers={"Content-Type": "application/json", **cabecalhos})


def test_integracao_sem_cabecalho_o_sdk_aceita_como_1_0(capsys):
    assert http_a2a({}).json()["error"]["code"] == -32001
    assert avisos_de_compatibilidade(capsys) == [AVISO_VERSAO]


def test_integracao_com_1_0_o_sdk_aceita_sem_aviso(capsys):
    assert http_a2a({"A2A-Version": "1.0"}).json()["error"]["code"] == -32001
    assert avisos_de_compatibilidade(capsys) == []


@pytest.mark.parametrize("valor,lembrete", [("0.3", "0.3"), ("", "0.3"), ("2.0", "2.0")])
def test_integracao_versao_incompativel_explicita_continua_recusada_com_32009(capsys, valor, lembrete):
    r = http_a2a({"A2A-Version": valor})
    assert r.json()["error"]["code"] == -32009 and f"'{lembrete}'" in r.json()["error"]["message"]
    assert avisos_de_compatibilidade(capsys) == []   # a recusa é do SDK; o middleware não interveio
