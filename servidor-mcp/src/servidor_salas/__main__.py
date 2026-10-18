"""Ponto de entrada: python -m servidor_salas"""
import uvicorn

from .config import dados_dir, porta, segredo_request_state
from .dominio import Dominio
from .middleware import ExigeVersaoProtocolo
from .server import criar_servidor


def main() -> None:
    dominio = Dominio(dados_dir())
    mcp = criar_servidor(dominio, segredo_request_state())
    app = ExigeVersaoProtocolo(mcp.streamable_http_app(stateless_http=True))
    uvicorn.run(app, host="127.0.0.1", port=porta(), log_level="warning")


if __name__ == "__main__":
    main()
