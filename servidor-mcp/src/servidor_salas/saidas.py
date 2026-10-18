# Formas de `structuredContent` das tools. Nomes de classe, campos e ordem seguem `exemplos/wire/01`
# (contrato oficial do starter): o `outputSchema` gerado precisa ser igual ao do contrato.
# Sem docstrings nas classes: elas entrariam como `description` no schema e o afastariam do contrato.
from __future__ import annotations

from pydantic import BaseModel


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


# Reserva concluída (`reservado: true`) ou recusa (`reservado: false` com `motivo`); campos ausentes ficam nulos.
class ReservaOut(BaseModel):
    reserva: str | None = None
    reservado: bool = True
    sala: str | None = None
    inicio: str | None = None
    fim: str | None = None
    responsavel: str | None = None
    politica: str | None = None
    motivo: str | None = None
