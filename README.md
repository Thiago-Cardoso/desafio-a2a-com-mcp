# A Ponte: um agente A2A com MCP por dentro

Duas pontas de uma mesma fronteira, em Python:

- `servidor-mcp/`: servidor MCP (Streamable HTTP, stateless) das cinco salas de reunião da Hill Valley Tech, com três tools, um resource e o ciclo MRTR na reserva.
- `agente/`: agente que é host MCP por dentro (consome o servidor acima) e servidor A2A v1.0 por fora (Agent Card, `SendMessage`, `GetTask`, Task passando por `TASK_STATE_INPUT_REQUIRED`).

`dados/`, `validador/` e `exemplos/` são do starter e não foram alterados.

## Como rodar

### Pré-requisitos

- Python 3.10 ou superior (verificado com 3.12 e 3.14)
- `git` e `pip` (já vem com o Python)
- Portas `7300` e `7301` livres

Sem Node, sem banco, sem LLM.

### 1. Clone e ambiente virtual

```bash
git clone https://github.com/Thiago-Cardoso/desafio-a2a-com-mcp.git
cd desafio-a2a-com-mcp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2. Dependências dos dois projetos

As versões estão travadas em `servidor-mcp/pyproject.toml` e `agente/pyproject.toml`. Os extras `test` trazem o `pytest` e o que os testes usam.

```bash
python -m pip install -e "./servidor-mcp[test]" -e "./agente[test]"
```

### 3. Segredo do `requestState`

O `requestState` é selado pelo servidor MCP (veja *Decisões técnicas*). O segredo vem **somente de uma variável de ambiente**, nunca do repositório, e precisa ter pelo menos 32 bytes.

Gere o segredo e exporte-o no primeiro terminal:

```bash
export REQUEST_STATE_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Para visualizar o valor gerado e copiá-lo para o segundo terminal, execute:

```bash
echo "$REQUEST_STATE_SECRET"
```

**Importante:** o comando `echo` exibe o segredo em texto puro. Não compartilhe esse valor, não o inclua no repositório e não o adicione aos logs ou à documentação. Gere um segredo novo para cada ambiente.

`token_hex(32)` produz 64 caracteres hexadecimais, correspondentes a 32 bytes de entropia. Sem a variável, ou com menos de 32 bytes, o servidor MCP recusa subir.

Quem lê o segredo é o servidor MCP. O agente trata o `requestState` como opaco e apenas o devolve, sem interpretar seu conteúdo.

Para executar o projeto, use o mesmo valor de `REQUEST_STATE_SECRET` nos dois terminais. Se o servidor MCP for reiniciado com o mesmo segredo, os `requestState` emitidos anteriormente continuam verificáveis, desde que ainda estejam dentro do prazo de validade.

Não gere um segredo novo entre o início de uma operação e sua retomada, pois isso pode invalidar os estados pausados existentes.

### 4. Servidor MCP (terminal 1)

```bash
source .venv/bin/activate
export REQUEST_STATE_SECRET="..."   # o mesmo valor do passo 3
python -m servidor_salas
```

Escuta em `http://127.0.0.1:7301/mcp`. Cada request vira uma linha JSON em stderr, com o `traceparent` recebido. Porta configurável por `PORTA_MCP`.

### 5. Agente A2A (terminal 2)

```bash
source .venv/bin/activate
export REQUEST_STATE_SECRET="..."   # o mesmo valor do passo 3
python -m agente
```

- JSON-RPC: `http://127.0.0.1:7300/a2a`
- Agent Card: `http://127.0.0.1:7300/.well-known/agent-card.json`

```bash
curl -s http://127.0.0.1:7300/.well-known/agent-card.json
```

Variáveis opcionais: `PORTA_A2A` (padrão `7300`), `URL_MCP` (padrão `http://127.0.0.1:7301/mcp`), `URL_PUBLICA_A2A` (endereço anunciado no card).

**Ordem de subida:** o servidor MCP primeiro, o agente depois. O agente só fala com o MCP quando recebe um `SendMessage`, mas subir nessa ordem evita erro no primeiro pedido.

### 6. Testes

Na raiz do repositório, com o ambiente virtual ativo (não precisam dos processos no ar):

```bash
python -m pytest agente/tests -v
python -m pytest servidor-mcp/tests -v
```

### 7. Validador oficial

Com os dois processos ativos, **recém-iniciados** (as reservas criadas por uma execução mudam o resultado da seguinte), em um terceiro terminal:

```bash
python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

Resultado esperado: 36 verificações `PASS` e código de saída `0` (`echo $?`). Para rodar de novo, encerre e suba os dois processos outra vez. A saída da última execução está em *Saída do validador*.

Duas exigências ficam fora do validador (veja `validador/README.md`): o `requestState` continuar válido depois de reiniciar o servidor MCP (use o mesmo `REQUEST_STATE_SECRET`) e o `traceparent` aparecer no stderr do servidor MCP (procure o trace-id que o validador imprime na primeira linha).

### 8. Encerrar

`Ctrl+C` em cada terminal. Para conferir que as portas ficaram livres:

```bash
lsof -nP -iTCP:7300 -iTCP:7301 -sTCP:LISTEN   # sem saída = livres
```

**Estado em memória.** Tudo é mantido em memória nos dois processos: as reservas (carregadas de `dados/reservas.json` ao subir e perdidas ao encerrar), as Tasks A2A e as pausas pendentes do agente. Reiniciar o **agente** perde as Tasks e as pausas; reiniciar o **servidor MCP** perde as reservas criadas, mas um `requestState` já emitido segue válido enquanto o segredo e o TTL (15 minutos) permitirem.

## Onde a ponte acontece

Em `agente/src/agente/executor.py`, classe `ExecutorReserva`. `_novo_pedido` abre a Task, chama a tool `reservar_sala` no servidor MCP e entrega o resultado a `_tratar`. Quando o servidor responde `InputRequiredResult` (sala ocupada), `_tratar` guarda o `requestState` e as alternativas em `self.pendencias[task_id]` e chama `_pausar`, que publica a mensagem e leva a Task a `TASK_STATE_INPUT_REQUIRED` (`up.requires_input`). Quando o cliente A2A responde na mesma Task, `execute` reivindica a pausa com `pendencias.pop` (só uma continuação por pausa) e `_continuar` repete a chamada MCP, com id JSON-RPC novo, devolvendo o `requestState` guardado em `request_state=` junto com o `input_responses` (aceite com a sala escolhida, ou `decline` na recusa). O `traceparent` do cliente A2A é lido dos cabeçalhos HTTP e reenviado em `_meta` de todo request MCP feito em nome da Task (`mcp_cliente.py`).

## Decisões técnicas

- **Proteção do `requestState`.** O servidor monta `RequestStateSecurity(keys=[segredo], ttl=900)` do SDK `mcp` (`servidor-mcp/src/servidor_salas/server.py`): o conteúdo é selado com cifra autenticada, e o que for adulterado, expirado ou de outro segredo é recusado com `-32602` (*Invalid or expired requestState*). O payload (`mrtr.selar`) é JSON legível por dentro do selo, mas não adulterável.
- **Validade.** 900 segundos (15 minutos) a partir da emissão.
- **Estado das Tasks.** `InMemoryTaskStore` do SDK A2A, estendido em `armazenamento.py` para não repetir mensagens no `history`. As pausas pendentes (`requestState`, alternativas, trace) ficam em um dicionário em memória, por `task_id`, o que mantém duas Tasks pausadas ao mesmo tempo isoladas uma da outra.
- **Transporte MCP stateless.** O servidor responde `input_required` em vez de pedir informação ao cliente no meio da execução. O agente anuncia apenas `elicitation: {form: {}}` em `io.modelcontextprotocol/clientCapabilities` (`mcp_cliente.capacidades_so_form`); sem a capability o servidor responde com o erro `-32021`.
- **Sem LLM.** O pedido tem formato fixo (`agente/src/agente/pedido.py`) e a decisão é por regra; pedido fora do formato é rejeitado com `-32602` antes de existir Task (`ValidaFormato`).
- **Desvio conhecido: cabeçalho `A2A-Version`.** A especificação A2A (§3.6.2) manda tratar a ausência do cabeçalho `A2A-Version` como `0.3`. O middleware `CompatibilidadeVersao` (`agente/src/agente/middleware.py`) trata a ausência como `1.0` no endpoint `/a2a` e registra um aviso em stderr, porque o validador oficial envia requests sem o cabeçalho. É um desvio deliberado de compatibilidade com o validador, restrito a esse endpoint; um cabeçalho presente nunca é alterado.
- **Task terminal.** `ManipuladorRecusaTerminal` recusa mensagem para Task em estado terminal antes de o SDK criar o `ActiveTask`, evitando tarefas pendentes na dependência `a2a-sdk` 1.2.2 (documentado no módulo).

## Saída do validador

Execução em clone limpo, com os dois processos recém-iniciados (`python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301`). Código de saída: `0`. O trace-id impresso aparece 8 vezes no stderr do servidor MCP.

```text
trace-id desta execucao: 1c655d2c069c8f7352d54c5f6b19175f
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```
