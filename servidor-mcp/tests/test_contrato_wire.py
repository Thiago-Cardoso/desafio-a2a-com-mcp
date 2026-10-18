"""C-A: o servidor segue o contrato oficial `exemplos/wire/01` (outputSchema) e responde no formato que ele declara.

As respostas são reais: o app MCP completo roda em processo (`TestClient`), com o `Dominio` carregado de `dados/`.
O contrato é lido do starter, sem cópia nem alteração.
"""
import json
import secrets
from pathlib import Path

import jsonschema
import pytest
from starlette.testclient import TestClient

from servidor_salas.dominio import Dominio
from servidor_salas.middleware import ExigeVersaoProtocolo
from servidor_salas.server import criar_servidor

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "exemplos" / "wire" / "01-tools-list.json"
pytestmark = pytest.mark.skipif(not CONTRATO.exists(), reason="exemplos/wire/01 ausente (fora do repositório do desafio)")

PROTO = "2026-07-28"


def meta(capacidade=None):
    return {"io.modelcontextprotocol/protocolVersion": PROTO,
            "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}} if capacidade is None else capacidade}


def schemas_do_contrato():
    ferramentas = json.loads(CONTRATO.read_text(encoding="utf-8"))["response"]["body"]["result"]["tools"]
    return {t["name"]: t["outputSchema"] for t in ferramentas}


class Cliente:
    def __init__(self, c):
        self.c = c
        self._n = 0

    def chamar(self, metodo, params, nome=None):
        self._n += 1
        cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": PROTO, "Mcp-Method": metodo}
        if nome:
            cab["Mcp-Name"] = nome
        r = self.c.post("/mcp", headers=cab, json={"jsonrpc": "2.0", "id": self._n, "method": metodo,
                                                   "params": {**params, "_meta": meta()}})
        return r.json()

    def tool(self, nome, argumentos, **extra):
        return self.chamar("tools/call", {"name": nome, "arguments": argumentos, **extra}, nome)


@pytest.fixture()
def cliente():
    servidor = criar_servidor(Dominio(RAIZ / "dados"), secrets.token_hex(32).encode())
    app = ExigeVersaoProtocolo(servidor.streamable_http_app(stateless_http=True))
    with TestClient(app, base_url="http://127.0.0.1:7301") as c:
        yield Cliente(c)


def valida(nome, resposta):
    resultado = resposta["result"]
    assert resultado.get("isError") in (None, False), resultado
    jsonschema.validate(resultado["structuredContent"], schemas_do_contrato()[nome])
    # O bloco de texto é o mesmo JSON do structuredContent (enunciado L166 e L169).
    assert json.loads(resultado["content"][0]["text"]) == resultado["structuredContent"]
    return resultado["structuredContent"]


def test_output_schema_servido_e_igual_ao_do_contrato(cliente):
    servidas = {t["name"]: t.get("outputSchema") for t in cliente.chamar("tools/list", {})["result"]["tools"]}
    contrato = schemas_do_contrato()
    assert set(servidas) == set(contrato) == {"listar_salas", "consultar_disponibilidade", "reservar_sala"}
    for nome in contrato:
        assert servidas[nome] == contrato[nome], f"outputSchema de {nome} diverge de exemplos/wire/01"


def test_listar_salas_valida_contra_o_contrato(cliente):
    dados = valida("listar_salas", cliente.tool("listar_salas", {}))
    assert [s["id"] for s in dados["salas"]][:2] == ["sala-aquario", "sala-porao"]


def test_consultar_sala_livre_valida_contra_o_contrato(cliente):
    dados = valida("consultar_disponibilidade", cliente.tool(
        "consultar_disponibilidade", {"sala": "sala-aquario", "inicio": "2026-11-03T09:00:00-03:00", "fim": "2026-11-03T10:00:00-03:00"}))
    assert dados == {"sala": "sala-aquario", "livre": True, "conflitos": []}


def test_consultar_com_conflito_usa_id_e_nao_traz_campos_extras(cliente):
    dados = valida("consultar_disponibilidade", cliente.tool(
        "consultar_disponibilidade", {"sala": "sala-garagem", "inicio": "2026-11-03T14:00:00-03:00", "fim": "2026-11-03T15:00:00-03:00"}))
    assert set(dados) == {"sala", "livre", "conflitos"}
    assert dados["sala"] == "sala-garagem" and dados["livre"] is False
    assert dados["conflitos"] == [{"id": "res-0001", "inicio": "2026-11-03T14:00:00-03:00",
                                   "fim": "2026-11-03T15:00:00-03:00", "responsavel": "Marty"}]


def test_reserva_concluida_valida_contra_o_contrato(cliente):
    dados = valida("reservar_sala", cliente.tool(
        "reservar_sala", {"sala": "sala-aquario", "inicio": "2026-11-03T09:00:00-03:00", "fim": "2026-11-03T10:00:00-03:00", "responsavel": "Doc"}))
    assert dados["reservado"] is True and dados["politica"] == "2026-11-01" and dados["motivo"] is None
    # enunciado L169: reserva, reservado, sala, inicio, fim, responsavel e politica
    assert {"reserva", "reservado", "sala", "inicio", "fim", "responsavel", "politica"} <= set(dados)


def test_recusa_valida_contra_o_contrato(cliente):
    args = {"sala": "sala-garagem", "inicio": "2026-11-03T14:00:00-03:00", "fim": "2026-11-03T15:00:00-03:00", "responsavel": "Marty"}
    pausa = cliente.tool("reservar_sala", args)["result"]
    assert pausa["resultType"] == "input_required"
    chave = next(iter(pausa["inputRequests"]))
    dados = valida("reservar_sala", cliente.tool(
        "reservar_sala", args, inputResponses={chave: {"action": "decline"}}, requestState=pausa["requestState"]))
    assert dados["reservado"] is False and dados["motivo"] and dados["reserva"] is None


def test_consultar_reflete_a_reserva_criada(cliente):
    cliente.tool("reservar_sala", {"sala": "sala-porao", "inicio": "2026-11-04T09:00:00-03:00", "fim": "2026-11-04T10:00:00-03:00", "responsavel": "Ana"})
    dados = valida("consultar_disponibilidade", cliente.tool(
        "consultar_disponibilidade", {"sala": "sala-porao", "inicio": "2026-11-04T09:30:00-03:00", "fim": "2026-11-04T10:30:00-03:00"}))
    assert dados["livre"] is False and dados["conflitos"][0]["responsavel"] == "Ana"


def test_tools_inteiras_e_server_info_iguais_ao_contrato(cliente):
    """Nome, descrição, inputSchema e outputSchema de cada tool, e o serverInfo, iguais a exemplos/wire/01."""
    esperado = json.loads(CONTRATO.read_text(encoding="utf-8"))["response"]["body"]["result"]
    obtido = cliente.chamar("tools/list", {})["result"]
    por_nome = {t["name"]: t for t in obtido["tools"]}
    for ferramenta in esperado["tools"]:
        assert por_nome[ferramenta["name"]] == ferramenta, f"{ferramenta['name']} diverge de exemplos/wire/01"
    info = "io.modelcontextprotocol/serverInfo"
    assert obtido["_meta"][info] == esperado["_meta"][info]


EXTREMOS = [("9999-12-31T23:00:00-05:00", "9999-12-31T23:30:00-05:00"), ("0001-01-01T00:30:00+05:00", "0001-01-01T01:00:00+05:00")]


@pytest.mark.parametrize("inicio,fim", EXTREMOS)
@pytest.mark.parametrize("tool,extra", [("consultar_disponibilidade", {}), ("reservar_sala", {"responsavel": "Ext"})])
def test_data_extrema_devolve_32602_sem_traceback_e_sem_mensagem_vazia(cliente, caplog, tool, extra, inicio, fim):
    """Datas com fuso explícito que estouram ao converter para São Paulo: erro de parâmetro, não falha interna."""
    import logging

    caplog.set_level(logging.DEBUG)
    resposta = cliente.chamar("tools/call", {"name": tool, "arguments": {"sala": "sala-aquario", "inicio": inicio, "fim": fim, **extra}}, tool)
    assert "result" not in resposta
    assert resposta["error"]["code"] == -32602
    assert "fora do intervalo suportado" in resposta["error"]["message"] and inicio in resposta["error"]["message"]
    assert not [r for r in caplog.records if r.exc_info], "o servidor registrou traceback"
