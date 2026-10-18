import pytest

from agente.pedido import escolha_valida, parse_pedido, pedido_valido


def test_pedido_formato_fixo():
    assert pedido_valido("reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Marty")


def test_pedido_fora_do_formato():
    assert not pedido_valido("reservar sala=sala-garagem")
    assert not pedido_valido("oi, quero reservar")


def test_parse_extrai_campos():
    dados = parse_pedido("reservar sala=sala-a inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Ana")
    assert dados == {"sala": "sala-a", "inicio": "2026-11-03T14:00:00-03:00",
                     "fim": "2026-11-03T15:00:00-03:00", "responsavel": "Ana"}


@pytest.mark.parametrize("texto,ok", [("escolha=sala-mirante", True), ("escolha=recusar", True), ("escolha=", False), ("sim", False)])
def test_escolha(texto, ok):
    assert escolha_valida(texto) is ok


def test_responsavel_aceita_espacos():
    # D6: responsavel é o restante da linha, respeitando o formato fixo do pedido.
    dados = parse_pedido("reservar sala=sala-a inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Ana Lima")
    assert dados["responsavel"] == "Ana Lima"
    assert pedido_valido("reservar sala=sala-a inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Dr. Who Jr")


@pytest.mark.parametrize("inicio,fim", [
    ("2026-13-45T14:00:00-03:00", "2026-13-45T15:00:00-03:00"),   # data inválida (D4)
    ("2026-13-45T14:00:00", "2026-11-03T15:00:00"),               # data inválida, sem fuso
    ("amanha", "2026-11-03T15:00:00-03:00"),
])
def test_data_invalida_fora_do_formato(inicio, fim):
    assert not pedido_valido(f"reservar sala=sala-a inicio={inicio} fim={fim} responsavel=Ana")


@pytest.mark.parametrize("inicio,fim", [
    ("2026-11-03T14:00:00", "2026-11-03T15:00:00"),               # sem fuso: aceito; o servidor aplica -03:00 (D3 revisada)
    ("2026-11-03T14:00:00-03:00", "2026-11-03T15:00:00"),         # mistura
    ("2026-11-03T17:00:00+00:00", "2026-11-03T18:00:00Z"),        # fuso explícito não é reinterpretado
])
def test_data_com_ou_sem_fuso_e_aceita_no_pedido(inicio, fim):
    texto = f"reservar sala=sala-a inicio={inicio} fim={fim} responsavel=Ana"
    assert pedido_valido(texto)
    assert parse_pedido(texto)["inicio"] == inicio and parse_pedido(texto)["fim"] == fim   # o agente repassa sem alterar


@pytest.mark.parametrize("inicio,fim", [
    ("9999-12-31T23:00:00-05:00", "9999-12-31T23:30:00-05:00"),    # reportado: estoura ao converter para São Paulo
    ("0001-01-01T00:30:00+05:00", "0001-01-01T01:00:00+05:00"),    # reportado
    ("2026-11-03T09:00:00-03:00", "9999-12-31T23:30:00-05:00"),    # só o fim é extremo
    ("9999-12-31T22:00:00-04:00", "9999-12-31T23:59:59-04:00"),    # São Paulo está 1 h à frente: cairia no ano 10000
])
def test_data_extrema_nao_convertivel_e_recusada_antes_da_task(inicio, fim):
    assert not pedido_valido(f"reservar sala=sala-a inicio={inicio} fim={fim} responsavel=Ana")


@pytest.mark.parametrize("inicio,fim", [
    ("9999-12-31T22:00:00Z", "9999-12-31T23:00:00Z"),
    ("0001-01-01T09:00:00", "0001-01-01T10:00:00"),
    ("2026-11-03T09:00:00-03:00", "2026-11-03T10:00:00-03:00"),    # caso comum continua válido
    ("9999-12-31T12:00:00-12:00", "9999-12-31T13:00:00-12:00"),    # 21:00 em São Paulo: existe, embora seja o ano 10000 em UTC
])
def test_data_extrema_convertivel_e_caso_comum_continuam_validos(inicio, fim):
    assert pedido_valido(f"reservar sala=sala-a inicio={inicio} fim={fim} responsavel=Ana")


def test_sufixo_z_vale_utc_e_pedido_aceito():
    # F-03: o `fromisoformat` do Python 3.10 não aceita `Z`; o agente normaliza antes de validar (12:00Z = 09:00 em São Paulo).
    assert pedido_valido("reservar sala=sala-a inicio=2026-11-03T12:00:00Z fim=2026-11-03T13:00:00Z responsavel=Ana")
    assert pedido_valido("reservar sala=sala-a inicio=2026-11-03T12:00:00z fim=2026-11-03T13:00:00z responsavel=Ana")
    assert not pedido_valido("reservar sala=sala-a inicio=9999-12-31T23:00:00-05:00 fim=9999-12-31T23:30:00-05:00 responsavel=Ana")
    assert not pedido_valido("reservar sala=sala-a inicio=2026-11-03TZ fim=2026-11-03T13:00:00Z responsavel=Ana")


def test_sufixo_z_com_parser_que_rejeita_z_como_no_python_310(monkeypatch):
    # Imita o `fromisoformat` do 3.10 (rejeita `Z`). Não substitui a execução em 3.10 real.
    from datetime import datetime
    import agente.pedido as modulo

    class Datetime310(datetime):
        @classmethod
        def fromisoformat(cls, texto):
            if texto[-1:] in ("Z", "z"):
                raise ValueError(texto)
            return datetime.fromisoformat(texto)

    monkeypatch.setattr(modulo, "datetime", Datetime310)
    assert modulo.pedido_valido("reservar sala=sala-a inicio=2026-11-03T12:00:00Z fim=2026-11-03T13:00:00Z responsavel=Ana")
