"""Regras de negócio das salas. Sem transporte: o agente não importa este módulo."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

FUSO = timezone(timedelta(hours=-3))
INICIO_JANELA = time(8, 0)
FIM_JANELA = time(20, 0)
DURACAO_MAXIMA = timedelta(hours=2)
MAX_ALTERNATIVAS = 3

MSG_SALA_INEXISTENTE = "Sala inexistente: {}"
MSG_FORA_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
MSG_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
MSG_INTERVALO_INVALIDO = "Intervalo invalido: fim deve ser posterior a inicio"
MSG_SEM_ALTERNATIVAS = "Sem alternativas disponiveis no intervalo"


class ErroNegocio(Exception):
    """Violação de regra de negócio. Vira `isError: true` na tool."""

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class ParametroInvalido(Exception):
    """Data em formato inválido. Vira erro de protocolo -32602."""


@dataclass(frozen=True)
class Sala:
    id: str
    nome: str
    capacidade: int
    recursos: tuple[str, ...]

    def para_dict(self) -> dict:
        return {"id": self.id, "nome": self.nome, "capacidade": self.capacidade, "recursos": list(self.recursos)}


@dataclass(frozen=True)
class Reserva:
    id: str
    sala: str
    inicio: datetime
    fim: datetime
    responsavel: str

    def para_dict(self) -> dict:
        return {"reserva": self.id, "sala": self.sala, "inicio": self.inicio.isoformat(),
                "fim": self.fim.isoformat(), "responsavel": self.responsavel}


DESLOCAMENTO_SP = timedelta(hours=-3)


def em_sao_paulo(data: datetime) -> datetime:
    """A mesma data no horário de São Paulo, somando só a diferença entre os deslocamentos.

    O `astimezone` do Python passa por UTC, o que estoura nos extremos do calendário mesmo quando o horário de São Paulo
    existe (por exemplo, 9999-12-31T12:00-12:00 é 21:00 em São Paulo, mas 24:00 em UTC). Os fusos de uma string ISO 8601
    são deslocamentos fixos, então a soma direta é exata. Só estoura se o horário de São Paulo não existe no calendário.
    """
    if data.utcoffset() == DESLOCAMENTO_SP:
        return data
    return (data.replace(tzinfo=None) + (DESLOCAMENTO_SP - data.utcoffset())).replace(tzinfo=FUSO)


def iso_com_z(texto: str) -> str:
    """O `fromisoformat` do Python 3.10 não aceita o sufixo `Z` (UTC); a partir do 3.11 aceita. Normaliza para `+00:00` em qualquer versão."""
    if isinstance(texto, str) and texto[-1:] in ("Z", "z"):
        return texto[:-1] + "+00:00"
    return texto


def _data(texto: str) -> datetime:
    """Data ISO 8601. Sem fuso, vale o horário de São Paulo, -03:00 (enunciado L87); com fuso explícito, o valor é preservado.

    Datas nos extremos do calendário (ano 1 ou 9999) com fuso explícito podem não ser convertíveis para São Paulo, que a
    janela de uso exige. Isso é erro de parâmetro (`-32602`), detectado aqui para que nenhuma regra receba uma data que estoure.
    """
    try:
        data = datetime.fromisoformat(iso_com_z(texto))
    except (TypeError, ValueError) as erro:
        raise ParametroInvalido(f"data invalida: {texto!r}") from erro
    if data.tzinfo is None:
        return data.replace(tzinfo=FUSO)
    try:
        em_sao_paulo(data)
    except OverflowError as erro:
        raise ParametroInvalido(f"data fora do intervalo suportado: {texto!r}") from erro
    return data


class Dominio:
    def __init__(self, dados: Path):
        salas = json.loads((dados / "salas.json").read_text(encoding="utf-8"))
        reservas = json.loads((dados / "reservas.json").read_text(encoding="utf-8"))
        politica = (dados / "politica-de-uso.md").read_text(encoding="utf-8")
        self.versao_politica = politica.splitlines()[0].split(":", 1)[1].strip()
        self.politica_texto = politica
        self.salas: dict[str, Sala] = {
            s["id"]: Sala(s["id"], s["nome"], s["capacidade"], tuple(s["recursos"])) for s in salas}
        self.reservas: list[Reserva] = [
            Reserva(r["id"], r["sala"], _data(r["inicio"]), _data(r["fim"]), r["responsavel"]) for r in reservas]
        self._contador = len(self.reservas)

    def salas_lista(self) -> list[dict]:
        return [sala.para_dict() for sala in self.salas.values()]

    def validar(self, sala_id: str, inicio: str, fim: str) -> tuple[Sala, datetime, datetime]:
        """Ordem: sala existe, intervalo válido, janela de uso, duração máxima."""
        if sala_id not in self.salas:
            raise ErroNegocio(MSG_SALA_INEXISTENTE.format(sala_id))
        ini, fi = _data(inicio), _data(fim)
        if fi <= ini:
            raise ErroNegocio(MSG_INTERVALO_INVALIDO)
        for ponto in (ini, fi):
            hora = em_sao_paulo(ponto).time()
            if not (INICIO_JANELA <= hora <= FIM_JANELA):
                raise ErroNegocio(MSG_FORA_JANELA)
        if fi - ini > DURACAO_MAXIMA:
            raise ErroNegocio(MSG_DURACAO)
        return self.salas[sala_id], ini, fi

    def conflitos(self, sala_id: str, ini: datetime, fi: datetime) -> list[Reserva]:
        return [r for r in self.reservas if r.sala == sala_id and r.inicio < fi and ini < r.fim]

    def alternativas(self, sala: Sala, ini: datetime, fi: datetime) -> list[str]:
        candidatas = [s for s in self.salas.values()
                      if s.id != sala.id and s.capacidade >= sala.capacidade and not self.conflitos(s.id, ini, fi)]
        candidatas.sort(key=lambda s: (s.capacidade, s.id))
        return [s.id for s in candidatas[:MAX_ALTERNATIVAS]]

    def reservar(self, sala_id: str, ini: datetime, fi: datetime, responsavel: str) -> Reserva:
        self._contador += 1
        reserva = Reserva(f"res-{self._contador:04d}", sala_id, ini, fi, responsavel)
        self.reservas.append(reserva)
        return reserva
