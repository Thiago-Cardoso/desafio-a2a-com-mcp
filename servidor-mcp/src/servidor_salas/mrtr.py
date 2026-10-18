"""Ciclo MRTR: forma da elicitação e do estado selado (o SDK faz a proteção AEAD)."""
import json

CHAVE_ESCOLHA = "escolha-sala"
MSG_ESCOLHA = "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."


def requisicao_escolha(alternativas: list[str]) -> dict:
    return {
        CHAVE_ESCOLHA: {
            "method": "elicitation/create",
            "params": {
                "mode": "form",
                "message": MSG_ESCOLHA,
                "requestedSchema": {
                    "type": "object",
                    "properties": {"sala": {"type": "string", "enum": alternativas}},
                    "required": ["sala"],
                },
            },
        }
    }


def selar(sala: str, inicio: str, fim: str, responsavel: str, alternativas: list[str]) -> str:
    """Payload em texto puro: o RequestStateSecurity do SDK o sela e verifica no retorno."""
    return json.dumps({"v": 1, "tool": "reservar_sala", "sala": sala, "inicio": inicio, "fim": fim,
                       "responsavel": responsavel, "alternativas": alternativas}, ensure_ascii=False)


def abrir(texto: str) -> dict:
    dados = json.loads(texto)
    if dados.get("v") != 1 or dados.get("tool") != "reservar_sala":
        raise ValueError("estado de outra versão ou tool")
    return dados
