"""Configuração do servidor MCP, lida do ambiente. Nunca imprime o segredo."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
PORTA_PADRAO = 7301


def dados_dir() -> Path:
    return Path(os.environ.get("DADOS_DIR", RAIZ / "dados"))


def segredo_request_state() -> bytes:
    valor = os.environ.get("REQUEST_STATE_SECRET", "")
    if not valor:
        raise SystemExit("REQUEST_STATE_SECRET ausente. Gere com: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
    dados = valor.encode()
    if len(dados) < 32:
        raise SystemExit("REQUEST_STATE_SECRET deve ter pelo menos 32 bytes.")
    return dados


def porta() -> int:
    return int(os.environ.get("PORTA_MCP", PORTA_PADRAO))
