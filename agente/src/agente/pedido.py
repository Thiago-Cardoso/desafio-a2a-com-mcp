"""Formato fixo do pedido e da escolha (enunciado, linhas 126–127).

`responsavel` é o restante da linha, então aceita espaços (D6). As datas são ISO 8601; o fuso, quando falta, é decidido pelo servidor (-03:00).
"""
import re
from datetime import datetime, timedelta

_DESLOCAMENTO_SP = timedelta(hours=-3)
_PEDIDO = re.compile(r"^reservar sala=(\S+) inicio=(\S+) fim=(\S+) responsavel=(.+)$")
_ESCOLHA = re.compile(r"^escolha=(\S+)$")
MSG_FORMATO = ("Pedido fora do formato. Use: reservar sala=<id> inicio=<iso8601> fim=<iso8601> "
               "responsavel=<nome>. Em pausa, responda: escolha=<id da sala> ou escolha=recusar")


def _iso_valido(texto: str) -> bool:
    """Data ISO 8601 que o servidor consegue converter para o horário de São Paulo (sem regra de negócio: só representabilidade)."""
    try:
        data = datetime.fromisoformat(texto[:-1] + "+00:00" if texto[-1:] in ("Z", "z") else texto)
        if data.tzinfo is not None:
            data.replace(tzinfo=None) + (_DESLOCAMENTO_SP - data.utcoffset())   # só soma o deslocamento; estoura se não existe em São Paulo
    except (ValueError, OverflowError):
        return False
    return True


def pedido_valido(texto: str) -> bool:
    partes = _PEDIDO.match(texto.strip())
    if not partes:
        return False
    inicio, fim, responsavel = partes.group(2), partes.group(3), partes.group(4)
    return _iso_valido(inicio) and _iso_valido(fim) and bool(responsavel.strip())


def escolha_valida(texto: str) -> bool:
    return bool(_ESCOLHA.match(texto.strip()))


def parse_pedido(texto: str) -> dict:
    partes = _PEDIDO.match(texto.strip())
    if not partes or not pedido_valido(texto):
        raise ValueError(MSG_FORMATO)
    sala, inicio, fim, responsavel = partes.groups()
    return {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel.strip()}


def valor_escolha(texto: str) -> str:
    return _ESCOLHA.match(texto.strip()).group(1)
