"""Configuração do agente, lida do ambiente."""
import os

PORTA_A2A_PADRAO = 7300


def url_mcp() -> str:
    return os.environ.get("URL_MCP", "http://127.0.0.1:7301/mcp")


def porta_a2a() -> int:
    return int(os.environ.get("PORTA_A2A", PORTA_A2A_PADRAO))


def url_publica_a2a() -> str:
    return os.environ.get("URL_PUBLICA_A2A", f"http://127.0.0.1:{porta_a2a()}/a2a")
