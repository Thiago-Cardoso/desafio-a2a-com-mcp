"""Handler A2A que recusa, antes do SDK, mensagem para Task em estado terminal.

No `a2a-sdk` 1.2.2, `DefaultRequestHandler` (v2) cria o `ActiveTask` e, só depois, descobre que a Task é terminal e
lança `UnsupportedOperationError` (-32004). Nesse caminho de erro, as duas `EventQueueSource` do `ActiveTask` não são
fechadas e seus `_dispatch_loop` ficam pendentes; quando o coletor de lixo os recolhe, o stderr recebe
`Task was destroyed but it is pending!` e `Failed to detach context`. A resposta ao cliente já era correta; o defeito é
da dependência e **não foi corrigido**. Esta classe só evita o caminho: consulta o estado no mesmo task store que o handler
usa (sem segunda fonte de verdade) e lança o mesmo erro do SDK, com a mesma mensagem, antes de o `ActiveTask` existir.
Tasks não terminais, inexistentes e mensagens sem `taskId` seguem direto para o SDK.
"""
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import a2a_pb2
from a2a.utils.errors import UnsupportedOperationError

_ESTADOS_TERMINAIS = frozenset({
    a2a_pb2.TaskState.TASK_STATE_COMPLETED,
    a2a_pb2.TaskState.TASK_STATE_FAILED,
    a2a_pb2.TaskState.TASK_STATE_CANCELED,
    a2a_pb2.TaskState.TASK_STATE_REJECTED,
})


class ManipuladorRecusaTerminal(DefaultRequestHandler):
    async def _recusar_se_terminal(self, params, context) -> None:
        id_tarefa = params.message.task_id
        if not id_tarefa:
            return
        tarefa = await self.task_store.get(id_tarefa, context)
        if tarefa is not None and tarefa.status.state in _ESTADOS_TERMINAIS:
            raise UnsupportedOperationError(
                message=f"Task {tarefa.id} is in terminal state: {a2a_pb2.TaskState.Name(tarefa.status.state)}")

    async def on_message_send(self, params, context):
        await self._recusar_se_terminal(params, context)
        return await super().on_message_send(params, context)

    async def on_message_send_stream(self, params, context):
        await self._recusar_se_terminal(params, context)
        async for evento in super().on_message_send_stream(params, context):
            yield evento
