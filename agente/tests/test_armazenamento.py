import asyncio

from a2a.server.context import ServerCallContext
from a2a.types import Part
from a2a.types import a2a_pb2 as pb

from agente.armazenamento import TaskStoreSemRepeticoes, remover_mensagens_repetidas


def msg(id_, texto, papel=pb.ROLE_AGENT):
    m = pb.Message(message_id=id_, role=papel)
    m.parts.append(Part(text=texto))
    return m


def tarefa_com(*mensagens):
    t = pb.Task(id="t1", context_id="c1")
    t.history.extend(mensagens)
    return t


def test_remove_repeticao_e_mantem_a_ordem_da_primeira_ocorrencia():
    # Efeito do SDK ao receber a continuação: a pausa (já no history) é movida de novo, e a escolha vem depois.
    t = tarefa_com(msg("u1", "pedido", pb.ROLE_USER), msg("p1", "alternativas: a, b"), msg("p1", "alternativas: a, b"), msg("u2", "escolha=a", pb.ROLE_USER))
    assert remover_mensagens_repetidas(t) is True
    assert [m.message_id for m in t.history] == ["u1", "p1", "u2"]


def test_sem_repeticao_nada_muda():
    t = tarefa_com(msg("u1", "pedido", pb.ROLE_USER), msg("p1", "alternativas: a"))
    assert remover_mensagens_repetidas(t) is False
    assert [m.message_id for m in t.history] == ["u1", "p1"]


def test_mensagens_distintas_com_o_mesmo_texto_sao_preservadas():
    # Duas pausas com o mesmo texto, mas ids diferentes, são mensagens diferentes (escolha inválida e nova pausa).
    t = tarefa_com(msg("p1", "alternativas: a"), msg("p2", "alternativas: a"))
    assert remover_mensagens_repetidas(t) is False
    assert len(t.history) == 2


def test_save_remove_repeticoes_no_proprio_objeto_e_persiste_limpo():
    # O TaskManager reutiliza o objeto passado ao save; limpá-lo no lugar vale também para a resposta em memória.
    store = TaskStoreSemRepeticoes()
    t = tarefa_com(msg("p1", "pausa"), msg("p1", "pausa"))
    ctx = ServerCallContext()
    asyncio.run(store.save(t, ctx))
    assert len(t.history) == 1
    salvo = asyncio.run(store.get("t1", ctx))
    assert [m.message_id for m in salvo.history] == ["p1"]
