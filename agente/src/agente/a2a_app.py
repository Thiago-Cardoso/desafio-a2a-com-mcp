"""Aplicação A2A: card, JSON-RPC em /a2a e middlewares de transporte."""
import json
from pathlib import Path

from google.protobuf.json_format import ParseDict
from starlette.applications import Starlette

from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types import a2a_pb2

from .armazenamento import TaskStoreSemRepeticoes
from .config import url_mcp, url_publica_a2a
from .executor import ExecutorReserva
from .manipulador import ManipuladorRecusaTerminal
from .mcp_cliente import ClienteMcp
from .middleware import CompatibilidadeVersao, ValidaFormato

RAIZ = Path(__file__).resolve().parents[3]


def _card() -> a2a_pb2.AgentCard:
    # Forma de referência: exemplos/wire/07-a2a-agent-card.json (starter). Só o endereço muda por ambiente.
    exemplo = json.loads((RAIZ / "exemplos" / "wire" / "07-a2a-agent-card.json").read_text(encoding="utf-8"))
    corpo = exemplo["response"]["body"]
    corpo["supportedInterfaces"][0]["url"] = url_publica_a2a()
    corpo["version"] = "1.0.0"
    return ParseDict(corpo, a2a_pb2.AgentCard(), ignore_unknown_fields=True)


def criar_app():
    pendencias: dict = {}
    card = _card()
    handler = ManipuladorRecusaTerminal(agent_executor=ExecutorReserva(ClienteMcp(url_mcp()), pendencias),
                                    task_store=TaskStoreSemRepeticoes(), agent_card=card)
    rotas = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/a2a")
    return CompatibilidadeVersao(ValidaFormato(Starlette(routes=rotas)))
