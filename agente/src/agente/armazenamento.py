"""Task store do agente: o do SDK, sem `messageId` repetido no `history`.

O SDK move a mensagem de `status.message` para o `history` a cada novo estado ou mensagem. A pausa e a mensagem final
são publicadas também em `WORKING` para constar no `history` já no momento em que ocorrem (como em `exemplos/wire/08`,
`09` e `10`), e por isso o SDK as moveria uma segunda vez. Este store, ponto de extensão público do SDK, mantém cada
`messageId` uma só vez, na ordem da primeira ocorrência. O `TaskManager` guarda e reutiliza o mesmo objeto que passa ao
`save`, então a correção vale também para as respostas montadas em memória.
"""
from a2a.server.tasks import InMemoryTaskStore


def remover_mensagens_repetidas(tarefa) -> bool:
    """Remove, no próprio objeto, as mensagens do `history` com `messageId` já visto. Devolve True se removeu alguma."""
    vistos = set()
    unicas = []
    for mensagem in tarefa.history:
        if mensagem.message_id in vistos:
            continue
        vistos.add(mensagem.message_id)
        unicas.append(mensagem)
    if len(unicas) == len(tarefa.history):
        return False
    copia = [m for m in unicas]
    del tarefa.history[:]
    tarefa.history.extend(copia)
    return True


class TaskStoreSemRepeticoes(InMemoryTaskStore):
    async def save(self, task, context):
        remover_mensagens_repetidas(task)
        return await super().save(task, context)
