"""Ponto de entrada: python -m agente"""
import uvicorn

from .a2a_app import criar_app
from .config import porta_a2a


def main() -> None:
    uvicorn.run(criar_app(), host="127.0.0.1", port=porta_a2a(), log_level="warning")


if __name__ == "__main__":
    main()
