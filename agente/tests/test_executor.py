import pytest

from agente.executor import FalhaDeExecucao, _trace_do_cabecalho, _valida_argumentos, _versao_politica

SCHEMA = {"type": "object", "required": ["sala", "inicio", "fim", "responsavel"]}


def test_descoberta_exige_argumentos_do_schema():
    # D5: os argumentos são checados contra o inputSchema descoberto no tools/list.
    _valida_argumentos(SCHEMA, {"sala": "s", "inicio": "i", "fim": "f", "responsavel": "r"})
    with pytest.raises(FalhaDeExecucao, match="responsavel"):
        _valida_argumentos(SCHEMA, {"sala": "s", "inicio": "i", "fim": "f"})


def test_versao_vem_da_primeira_linha_do_resource():
    # F-03: a versão lida do resource é a que vai ao artifact.
    assert _versao_politica("versao: 2026-11-01\n\n- regra") == "2026-11-01"
    with pytest.raises(FalhaDeExecucao):
        _versao_politica("sem versao aqui")


def test_trace_do_cabecalho_so_aceita_formato_w3c():
    assert _trace_do_cabecalho({"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}) == "a" * 32
    assert _trace_do_cabecalho({"traceparent": "lixo"}) is None
    assert _trace_do_cabecalho({}) is None
