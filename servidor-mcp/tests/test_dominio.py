from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from servidor_salas.dominio import (
    MSG_DURACAO, MSG_FORA_JANELA, MSG_INTERVALO_INVALIDO, MSG_SALA_INEXISTENTE, MSG_SEM_ALTERNATIVAS,
    Dominio, ErroNegocio,
)

DADOS = Path(__file__).resolve().parents[2] / "dados"
FUSO = timezone(timedelta(hours=-3))


@pytest.fixture
def dominio():
    return Dominio(DADOS)


def dia(h, m=0):
    return datetime(2026, 11, 3, h, m, tzinfo=FUSO).isoformat()


def test_versao_da_politica_vem_da_primeira_linha(dominio):
    assert dominio.versao_politica == "2026-11-01"


def test_sala_inexistente(dominio):
    with pytest.raises(ErroNegocio) as e:
        dominio.validar("sala-x", dia(9), dia(10))
    assert e.value.mensagem == MSG_SALA_INEXISTENTE.format("sala-x")


def test_intervalo_invertido_ou_vazio(dominio):
    for ini, fim in [(dia(10), dia(10)), (dia(11), dia(10))]:
        with pytest.raises(ErroNegocio) as e:
            dominio.validar("sala-aquario", ini, fim)
        assert e.value.mensagem == MSG_INTERVALO_INVALIDO


def test_janela_de_uso_limites_exatos(dominio):
    dominio.validar("sala-aquario", dia(8), dia(9))          # 08:00 é permitido
    dominio.validar("sala-aquario", dia(19), dia(20))         # 20:00 é permitido
    for ini, fim in [(dia(7, 59), dia(8, 30)), (dia(19, 30), dia(20, 1))]:
        with pytest.raises(ErroNegocio) as e:
            dominio.validar("sala-aquario", ini, fim)
        assert e.value.mensagem == MSG_FORA_JANELA


def test_duracao_maxima_de_duas_horas(dominio):
    dominio.validar("sala-aquario", dia(10), dia(12))         # exatamente 2 h é permitido
    with pytest.raises(ErroNegocio) as e:
        dominio.validar("sala-aquario", dia(10), dia(12, 1))
    assert e.value.mensagem == MSG_DURACAO


def test_sobreposicao_e_encostar_nao_conflita(dominio):
    # res-0001 é sala-garagem 14:00–15:00
    assert dominio.conflitos("sala-garagem", *dominio.validar("sala-garagem", dia(14, 30), dia(15, 30))[1:])
    assert not dominio.conflitos("sala-garagem", *dominio.validar("sala-garagem", dia(15), dia(16))[1:])


def test_alternativas_exemplo_do_enunciado(dominio):
    sala, ini, fi = dominio.validar("sala-garagem", dia(14), dia(15))
    assert dominio.alternativas(sala, ini, fi) == ["sala-fusca", "sala-mirante"]


def test_alternativas_limite_de_tres_e_ordem(dominio):
    sala, ini, fi = dominio.validar("sala-aquario", dia(9), dia(10))
    alts = dominio.alternativas(sala, ini, fi)
    assert len(alts) <= 3
    assert alts == sorted(alts, key=lambda s: (dominio.salas[s].capacidade, s))


def test_reserva_visivel_para_consultas_seguintes(dominio):
    sala, ini, fi = dominio.validar("sala-aquario", dia(9), dia(10))
    dominio.reservar("sala-aquario", ini, fi, "Teste")
    assert dominio.conflitos("sala-aquario", ini, fi)


def test_reserva_no_passado_e_permitida(dominio):
    sala, ini, fi = dominio.validar("sala-porao", datetime(2020, 1, 2, 9, tzinfo=FUSO).isoformat(),
                                    datetime(2020, 1, 2, 10, tzinfo=FUSO).isoformat())
    assert dominio.reservar("sala-porao", ini, fi, "Historico").sala == "sala-porao"


def sem_fuso(h, m=0):
    return datetime(2026, 11, 3, h, m).isoformat()          # naive: sem fuso


def test_data_sem_fuso_vale_o_horario_de_sao_paulo():
    # D3 (revisada): sem fuso, -03:00 (enunciado L87). Equivale ao mesmo instante com o fuso explícito.
    from servidor_salas.dominio import _data

    d = _data("2026-11-03T14:00:00")
    assert d.utcoffset() == timedelta(hours=-3) and d == _data("2026-11-03T14:00:00-03:00")


def test_fuso_explicito_e_preservado_e_nao_reinterpretado():
    from servidor_salas.dominio import _data

    utc = _data("2026-11-03T17:00:00+00:00")
    assert utc.utcoffset() == timedelta(0) and utc == _data("2026-11-03T14:00:00-03:00")   # mesmo instante
    assert _data("2026-11-03T17:00:00Z").utcoffset() == timedelta(0)
    leste = _data("2026-11-03T14:00:00+09:00")
    assert leste.utcoffset() == timedelta(hours=9) and leste != _data("2026-11-03T14:00:00-03:00")


@pytest.mark.parametrize("inicio,fim,erro", [
    (sem_fuso(8, 0), sem_fuso(9, 0), None),                    # limite inferior da janela, sem fuso
    (sem_fuso(7, 59), sem_fuso(8, 30), "fora"),
    (sem_fuso(19, 0), sem_fuso(20, 0), None),                  # limite superior da janela, sem fuso
    (sem_fuso(19, 30), sem_fuso(20, 1), "fora"),
    (sem_fuso(9, 0), sem_fuso(11, 0), None),                   # exatamente 2 h
    (sem_fuso(9, 0), sem_fuso(11, 1), "duracao"),
    ("2026-11-03T11:00:00+00:00", "2026-11-03T12:00:00+00:00", None),    # 08:00 em São Paulo: fuso explícito preservado
    ("2026-11-03T10:59:00+00:00", "2026-11-03T12:00:00+00:00", "fora"),  # 07:59 em São Paulo
    ("2026-11-03T22:00:00+00:00", "2026-11-03T23:00:00+00:00", None),    # 19:00 a 20:00 em São Paulo
    ("2026-11-03T22:30:00+00:00", "2026-11-03T23:01:00+00:00", "fora"),  # termina 20:01 em São Paulo
])
def test_janela_e_duracao_com_e_sem_fuso(dominio, inicio, fim, erro):
    from servidor_salas.dominio import MSG_DURACAO, MSG_FORA_JANELA

    if erro is None:
        dominio.validar("sala-aquario", inicio, fim)
        return
    with pytest.raises(ErroNegocio) as exc:
        dominio.validar("sala-aquario", inicio, fim)
    assert exc.value.mensagem == (MSG_FORA_JANELA if erro == "fora" else MSG_DURACAO)


def test_data_sem_fuso_conflita_com_reserva_do_starter(dominio):
    # Antes da D3 revisada, comparar data sem fuso com reserva com fuso causava TypeError e deixava a sala inutilizável.
    _, ini, fi = dominio.validar("sala-garagem", sem_fuso(14, 0), sem_fuso(15, 0))
    assert [r.id for r in dominio.conflitos("sala-garagem", ini, fi)] == ["res-0001"]
    dominio.reservar("sala-aquario", *dominio.validar("sala-aquario", sem_fuso(9, 0), sem_fuso(10, 0))[1:], "Ana")
    _, ini2, fi2 = dominio.validar("sala-aquario", dia(9, 30), dia(10, 30))
    assert len(dominio.conflitos("sala-aquario", ini2, fi2)) == 1       # a reserva criada sem fuso aparece para quem usa fuso


def test_data_que_nao_e_iso_continua_sendo_parametro_invalido(dominio):
    from servidor_salas.dominio import ParametroInvalido

    for texto in ("2026-13-45T10:00:00", "amanha", ""):
        with pytest.raises(ParametroInvalido):
            dominio.validar("sala-aquario", texto, dia(10))


def test_saidas_declaram_schema_das_tools():
    # C1: as três tools geram outputSchema a partir dos modelos de saída.
    from servidor_salas.saidas import Disponibilidade, ListaDeSalas, ReservaOut

    assert "salas" in ListaDeSalas.model_json_schema()["properties"]
    assert {"sala", "livre", "conflitos"} == set(Disponibilidade.model_json_schema()["properties"])
    assert "required" not in ReservaOut.model_json_schema()  # contrato wire/01: reservado tem padrão true


EXTREMAS_INVALIDAS = [
    "9999-12-31T23:00:00-05:00",   # reportado: UTC cairia no ano 10000
    "0001-01-01T00:30:00+05:00",   # reportado: UTC cairia no ano 0
    "0001-01-01T00:00:00+14:00",
    "0001-01-01T00:00:00Z",        # converter para -03:00 volta ao ano 0
    "9999-12-31T23:59:59.999999-12:00",
    "9999-12-31T23:59:59-04:00",   # São Paulo está 1 h à frente de -04:00: cairia no ano 10000
]
EXTREMAS_VALIDAS = [
    "9999-12-31T22:00:00Z",        # converter para -03:00 só retrocede
    "9999-12-31T23:59:59-03:00",   # já está em São Paulo
    "0001-01-01T09:00:00",         # sem fuso vale -03:00, sem conversão
    "0001-01-02T20:00:00+14:00",   # 03:00 em São Paulo, ainda no ano 1
    "9999-12-31T12:00:00-12:00",   # 21:00 em São Paulo; por UTC seria o ano 10000, mas o horário de São Paulo existe
    "9999-12-31T23:59:59-02:30",   # 23:29:59 em São Paulo
]


@pytest.mark.parametrize("texto", EXTREMAS_INVALIDAS)
def test_data_extrema_nao_convertivel_e_parametro_invalido(texto):
    from servidor_salas.dominio import ParametroInvalido, _data

    with pytest.raises(ParametroInvalido) as exc:
        _data(texto)
    assert "fora do intervalo suportado" in str(exc.value) and texto in str(exc.value)


@pytest.mark.parametrize("texto", EXTREMAS_VALIDAS)
def test_data_extrema_convertivel_continua_valida(texto):
    from servidor_salas.dominio import _data

    assert _data(texto).tzinfo is not None


def test_validar_nunca_deixa_overflow_escapar(dominio):
    from servidor_salas.dominio import ParametroInvalido

    for ini in EXTREMAS_INVALIDAS:
        with pytest.raises(ParametroInvalido):
            dominio.validar("sala-aquario", ini, ini)
        with pytest.raises(ParametroInvalido):
            dominio.validar("sala-aquario", dia(9), ini)       # o extremo pode estar só no fim
    for ini in EXTREMAS_VALIDAS:                                   # válidas: caem em ErroNegocio ou passam, nunca em OverflowError
        try:
            dominio.validar("sala-aquario", ini, ini)
        except ErroNegocio:
            pass


def test_varredura_de_extremos_so_recusa_o_que_nao_e_representavel_em_sao_paulo(dominio):
    """Combina anos, horas e fusos extremos. Oráculo independente do código: o horário de São Paulo é calculado por aritmética
    direta, num único passo (sem `astimezone` e sem passar por UTC). A data é recusada como "fora do intervalo" se, e somente se, esse horário não existe no calendário."""
    from servidor_salas.dominio import ParametroInvalido

    anos = ("0001-01-01", "0001-01-02", "0001-12-31", "0002-06-15", "9998-06-15", "9999-01-01", "9999-12-30", "9999-12-31")
    horas = ("00:00:00", "00:00:00.000001", "09:00:00", "12:00:00", "20:00:00", "23:59:59", "23:59:59.999999")
    fusos = ("", "Z", "-03:00", "+00:00", "-12:00", "+14:00", "-23:59", "+23:59", "+05:30", "-02:30")
    recusadas = aceitas = 0
    for ano in anos:
        for hora in horas:
            for fuso in fusos:
                texto = f"{ano}T{hora}{fuso}"
                bruto = datetime.fromisoformat(texto)
                deslocamento = bruto.utcoffset() if bruto.tzinfo is not None else timedelta(hours=-3)
                try:
                    bruto.replace(tzinfo=None) + (timedelta(hours=-3) - deslocamento)   # um só passo: sem UTC intermediário
                    representavel = True
                except OverflowError:
                    representavel = False
                try:
                    dominio.validar("sala-aquario", texto, dia(10))
                    resultado = "ok"
                except ParametroInvalido as erro:
                    resultado = "fora do intervalo" if "fora do intervalo suportado" in str(erro) else f"parametro: {erro}"
                except ErroNegocio:
                    resultado = "ok"                                   # regra de negócio (janela, duração): a data foi aceita como data
                assert (resultado == "fora do intervalo") == (not representavel), (texto, resultado, representavel)
                recusadas += not representavel
                aceitas += representavel
    assert recusadas > 0 and aceitas > 0                                 # a varredura exercita os dois lados


def test_sufixo_z_normalizado_para_python_310():
    """O `fromisoformat` do 3.10 não aceita `Z`; o domínio troca por `+00:00` antes de interpretar."""
    from servidor_salas.dominio import iso_com_z
    assert iso_com_z("2026-11-03T10:00:00Z") == "2026-11-03T10:00:00+00:00"
    assert iso_com_z("2026-11-03T10:00:00z") == "2026-11-03T10:00:00+00:00"
    assert iso_com_z("2026-11-03T10:00:00-03:00") == "2026-11-03T10:00:00-03:00"


def test_sufixo_z_vale_utc_e_deslocamentos_preservados():
    # F-03: `Z` é UTC (12:00Z = 09:00 em São Paulo); offset explícito é preservado; sem fuso vale -03:00.
    from servidor_salas.dominio import ParametroInvalido, _data, em_sao_paulo
    assert _data("2026-11-03T12:00:00Z").utcoffset() == timedelta(0)
    assert em_sao_paulo(_data("2026-11-03T12:00:00Z")).hour == 9
    assert _data("2026-11-03T12:00:00z").utcoffset() == timedelta(0)
    assert _data("2026-11-03T12:00:00+05:00").utcoffset() == timedelta(hours=5)
    assert _data("2026-11-03T12:00:00").utcoffset() == timedelta(hours=-3)
    with pytest.raises(ParametroInvalido):
        _data("2026-11-03TZ")
    with pytest.raises(ParametroInvalido):
        _data("Z")


class _DatetimeComoPython310(datetime):
    """Imita o `fromisoformat` do Python 3.10, que rejeita o sufixo `Z`. Não substitui a execução em 3.10 real."""

    @classmethod
    def fromisoformat(cls, texto):
        if texto[-1:] in ("Z", "z"):
            raise ValueError(f"Invalid isoformat string: {texto!r}")
        return datetime.fromisoformat(texto)


def test_sufixo_z_com_parser_que_rejeita_z_como_no_python_310(monkeypatch):
    import servidor_salas.dominio as dominio
    monkeypatch.setattr(dominio, "datetime", _DatetimeComoPython310)
    assert dominio._data("2026-11-03T12:00:00Z").utcoffset() == timedelta(0)
    assert dominio._data("2026-11-03T12:00:00-03:00").utcoffset() == timedelta(hours=-3)
