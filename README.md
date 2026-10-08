# E-commerce distribuido: microsservicos, REST, SSE e RabbitMQ

Trabalho de Sistemas Distribuidos (UTFPR / Profa. Ana Cristina Kochem Vendramin).

Aplicacao Web completa em **microsservicos**, com **arquitetura orientada a
eventos** e **assinatura digital com criptografia assimetrica**. O Trab1 era um
backend AMQP puro com menu de terminal; o Trab2 poe na frente dele um
**frontend web**, um **API Gateway REST**, um canal **SSE** de notificacoes em
tempo real, um **Mock de Pagamento** externo com **webhook** e uma **API
externa de e-mail**.

A regra do Trab1 continua valendo no miolo: **nenhum microsservico de negocio
chama outro diretamente** -- tudo passa pelo RabbitMQ. O HTTP aparece so nas
tres fronteiras que a arquitetura do Trab2 autoriza, e nenhuma delas carrega
regra de negocio entre servicos:

| Chamada HTTP | Por que nao e evento |
|---|---|
| frontend -> gateway (REST + SSE) | e a fronteira com o navegador |
| gateway -> `ms_estoque` `GET /produtos` | leitura de catalogo, exigida pelo enunciado |
| `ms_pagamento` -> Mock -> webhook | o provedor de pagamento e um sistema de terceiros |
| `ms_promocoes` -> Resend | API externa de e-mail |

## Arquitetura

```
                   navegador (React + Vite, :5173)
                        |  REST          ^ SSE
                        v                |
         ms_principal / API Gateway (:8000) --REST--> ms_estoque (:8002)
                        |                                  (SQLite)
                 [ RabbitMQ :5672 ]
             /          |           \            \
      ms_estoque   ms_pagamento   ms_entrega   ms_promocoes
                     |     ^                        |
               REST  |     | Webhook          REST  v
                     v     |                  api.resend.com
              mock_pagamento (:8004)
```

## Processos

| Processo | Porta | Fila propria | Consome | Publica |
|---|---|---|---|---|
| `ms_principal` (gateway) | 8000 | `fila.principal` | `pedido.estoque_ok`, `estoque.indisponivel`, `pagamento.pendente`, `pagamento.aprovado`, `pagamento.recusado`, `pedido.enviado` | `pedido.criado`, `pedido.excluido`, `interesse.promocao` |
| `ms_estoque` | 8002 | `fila.estoque` | `pedido.criado`, `pedido.excluido` | `pedido.estoque_ok`, `estoque.indisponivel` |
| `ms_pagamento` | 8003 | `fila.pagamento` | `pedido.estoque_ok` | `pagamento.pendente`, `pagamento.aprovado`, `pagamento.recusado` |
| `ms_entrega` | — | `fila.entrega` | `pagamento.aprovado` | `pedido.enviado` |
| `ms_promocoes` | — | `fila.promocoes` | `interesse.promocao`, `promocao.categoria.*` | `promocao.categoria.{A,B,C}` |
| `mock_pagamento` | 8004 | — (nao fala AMQP) | — | — |
| `frontend` | 5173 | — | SSE do gateway | REST para o gateway |

Exchanges: **`eCommerce`** (direct) e **`Promocoes`** (topic). Nenhuma fanout.
Cada consumidor declara a SUA fila (`durable=True`) e faz os proprios bindings.

O `ms_promocoes` tem **uma fila com dois bindings em exchanges diferentes**:
recebe `interesse.promocao` da direct e `promocao.categoria.*` da topic. Ele
consome a propria promocao que acabou de publicar -- e o que mantem geracao e
notificacao desacopladas e preserva o topic exchange com curinga, que os
consumidores C1/C2 do Trab1 demonstravam e que sairam da arquitetura do Trab2.

## Endpoints REST

Documentacao interativa (gerada pelo FastAPI): <http://localhost:8000/docs>.

| Metodo | Rota | O que faz |
|---|---|---|
| `GET` | `/api/produtos` | lista produtos **com saldo**, consultando o `ms_estoque` via REST |
| `POST` | `/api/pedidos` | cria o pedido e publica `pedido.criado` |
| `GET` | `/api/pedidos?clienteId=` | pedidos do cliente |
| `DELETE` | `/api/pedidos/{id}` | publica `pedido.excluido` (404 se nao existe, 409 se ja enviado/cancelado) |
| `POST` | `/api/interesses` | publica `interesse.promocao` com `acao=registrar` |
| `DELETE` | `/api/interesses?email=` | publica `interesse.promocao` com `acao=cancelar` |
| `GET` | `/api/categorias` | categorias disponiveis |
| `GET` | `/api/eventos/{clienteId}` | **SSE**: toda mudanca de estado dos pedidos do cliente |
| `GET` | `/health` | diz se a thread do consumidor continua viva |

Nos demais processos: `GET /produtos` (estoque), `POST /webhook/pagamento`
(pagamento), `POST /cobrancas` + `GET /checkout/{id}` (mock).

## Envelope do evento

```json
{
  "producer":  "ms_estoque",
  "event":     "pedido.estoque_ok",
  "timestamp": "2026-09-11T13:04:55+00:00",
  "payload":   { "pedidoId": "PED-A3F1-001", "itens": [], "total": 0.0 },
  "signature": "<base64>"
}
```

A assinatura cobre os **quatro** primeiros campos, nao apenas o `payload`
(ver "Decisoes de projeto", item 1).

## Estrutura

```
ecommerce-mom/
├── common/
│   ├── eventos.py        # Evento (StrEnum): routing keys da exchange eCommerce
│   ├── envelope.py       # Envelope + serializacao canonica (canon)
│   ├── crypto.py         # hash, assinatura, verificacao, chaves
│   ├── service.py        # conexao, topologia, Publisher, PublisherHTTP, Microservice
│   ├── http.py           # app FastAPI, lifespan com consumidor, cliente httpx
│   └── catalogo.py       # dados cadastrais dos produtos (sem estoque)
├── ms_principal/         # API Gateway: REST + SSE + consumidor
│   ├── main.py           #   bootstrap (uvicorn)
│   ├── api.py            #   rotas REST e SSE
│   ├── consumidor.py     #   MsPrincipal: evento -> estado -> SSE
│   ├── sse.py            #   barramento de assinantes
│   ├── store.py          #   PedidoStore e Status
│   └── keys/
├── ms_estoque/           # consumidor + GET /produtos
│   ├── main.py
│   ├── estoque.py        #   persistencia SQLite (WAL)
│   └── keys/
├── ms_pagamento/         # consumidor + POST /webhook/pagamento
├── ms_entrega/
├── ms_promocoes/         # interesses + e-mail (Resend)
│   ├── main.py
│   ├── interesses.py
│   └── notificacao.py
├── mock_pagamento/       # sistema EXTERNO: sem chave, sem AMQP
├── frontend/             # React + Vite + TypeScript
│   └── src/
│       ├── App.tsx  api.ts  useSSE.ts  types.ts  styles.css
│       └── components/Catalogo.tsx  Pedidos.tsx  Promocoes.tsx
├── tools/
│   ├── gen_keys.py       # gera os 5 pares e distribui as publicas
│   ├── test_crypto.py    # 9 verificacoes de assinatura, sem broker
│   ├── smoke_test.py     # fluxo ponta a ponta pela API, sem navegador
│   └── test_assinatura_invalida.py
├── run_services.sh / .ps1
├── docker-compose.yml
└── .env.example
```

## Fluxo de um pedido

```
  navegador --POST /api/pedidos--> gateway --pedido.criado--> ms_estoque
      ^                               |                            |
      |  SSE                          |<---- pedido.estoque_ok ----'
      |                               |            |
      |                               |            '--> ms_pagamento
      |                               |                     |
      |                               |                POST /cobrancas
      |                               |                     v
      |                               |              mock_pagamento
      |<-- pagamento.pendente --------|<-- pagamento.pendente ---'
      |      (checkoutUrl)            |
      |                               |
  usuario abre a aba e clica          |
      |                               |
      '--> mock --webhook--> ms_pagamento --pagamento.aprovado--> ms_entrega
                                      |                                |
      <------ SSE ------- gateway <---'<------- pedido.enviado --------'
```

O `pedido.excluido` sai em quatro situacoes: o usuario exclui pela tela, o
`ms_estoque` avisa `estoque.indisponivel`, o `ms_pagamento` recusa, ou a
cobranca nem chega a abrir porque o Mock esta fora. Nos tres ultimos casos quem
publica e o `ms_principal`, ao consumir o evento.

Uma diferenca pratica em relacao ao Trab1: la o fluxo inteiro terminava em
~15 ms e os estados intermediarios nunca eram vistos. Agora o pedido **para** em
`AGUARDANDO_PAGAMENTO` ate alguem clicar no Mock, entao cada transicao aparece
na tela, uma a uma, pelo SSE.

---

## Como rodar (Linux / macOS)

### 1. Broker

```bash
docker compose up -d          # RabbitMQ em localhost:5672
                              # painel: http://localhost:15672 (guest/guest)
```

### 2. Dependencias e chaves

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tools.gen_keys        # gera os 5 pares RSA-2048

cd frontend && npm install && cd ..
```

`gen_keys` coloca, em cada `<servico>/keys/`, a chave privada do servico e as
chaves publicas de **todos** os microsservicos. Rodar de novo nao sobrescreve:
use `--force` se quiser novas chaves. O `mock_pagamento` nao entra: ele e um
sistema externo, nao publica no broker e nao tem chave.

### 3. Os 6 processos do backend + o frontend

**Para a defesa, use um terminal por processo** (torna visivel que sao
processos independentes):

```bash
.venv/bin/python -m ms_estoque.main        # :8002
.venv/bin/python -m mock_pagamento.main    # :8004
.venv/bin/python -m ms_pagamento.main      # :8003
.venv/bin/python -m ms_entrega.main
.venv/bin/python -m ms_promocoes.main
.venv/bin/python -m ms_principal.main      # :8000  (API Gateway)

cd frontend && npm run dev                 # :5173  (a interface)
```

Atalho durante o desenvolvimento:

```bash
./run_services.sh start      # sobe os 6 do backend em background (logs/)
./run_services.sh logs       # acompanha todos os logs
./run_services.sh stop
cd frontend && npm run dev
```

Abra <http://localhost:5173>.

### 4. Variaveis de ambiente

Copie `.env.example` para `.env` (ja ignorado pelo git) ou exporte na mao.

| Variavel | Padrao | Efeito |
|---|---|---|
| `RESEND_API_KEY` | *(vazio)* | sem ela, o e-mail entra em **DRY-RUN** e so aparece no log |
| `RESEND_FROM` | `onboarding@resend.dev` | remetente; o dominio padrao so entrega para o dono da conta |
| `MOCK_WEBHOOK_SECRET` | `segredo-de-demonstracao` | segredo compartilhado entre o Mock e o webhook |
| `INTERVALO_PROMOCAO` | `8` | segundos entre promocoes |
| `GATEWAY_PORTA` / `PAGAMENTO_PORTA` / `MOCK_PORTA` | `8000` / `8003` / `8004` | portas HTTP |
| `ESTOQUE_URL` / `MOCK_URL` | `localhost:8002` / `localhost:8004` | enderecos consultados |
| `RABBIT_HOST` / `RABBIT_PORT` | `localhost` / `5672` | endereco do broker |
| `RABBIT_USER` / `RABBIT_PASS` | `guest` / `guest` | credenciais do broker |

**A chave do Resend nunca vai para o codigo nem para arquivo versionado.** Ela
e lida da variavel de ambiente -- em producao, vinda de um gerenciador de
segredos. O Resend autentica so por API key (nao oferece OAuth, service account
nem IAM role), entao a variavel de ambiente e a melhor opcao disponivel. Sem
ela o sistema roda inteiro, em DRY-RUN.

### Estoque inicial

`P1=10 P2=5 P3=0 P4=3 P5=7 P6=2`, semeado no SQLite no primeiro boot. O `P3`
comeca zerado de proposito -- e o caminho mais rapido para demonstrar
`estoque.indisponivel`. Para voltar ao estado inicial, apague
`ms_estoque/estoque.db` com o servico parado.

---
## Como rodar no Windows (RabbitMQ nativo, sem Docker)

O Docker so e usado para subir o broker. No Windows da para instalar o RabbitMQ
nativo -- ele roda sobre a maquina virtual do Erlang -- e o resto do projeto
nao muda: os processos continuam falando com `localhost:5672`.

### 1. Erlang/OTP (instalar ANTES do RabbitMQ)

Baixe o instalador 64-bit em <https://www.erlang.org/downloads> (OTP 26.2.x, a
faixa suportada pelo RabbitMQ 3.13) e execute **como Administrador** -- e isso
que grava a variavel `ERLANG_HOME` para a maquina toda. Instalado como usuario
comum, o servico do RabbitMQ nao encontra o Erlang e nao sobe.

Confira num prompt novo:

```cmd
echo %ERLANG_HOME%
erl -version
```

### 2. RabbitMQ Server

Baixe `rabbitmq-server-3.13.x.exe` em
<https://github.com/rabbitmq/rabbitmq-server/releases> e execute **como
Administrador**. O instalador ja registra e inicia o servico do Windows
`RabbitMQ`. O firewall vai perguntar sobre o `erl.exe` -- libere.

No menu Iniciar, abra **"RabbitMQ Command Prompt (sbin dir)"** como
Administrador e habilite o painel web:

```cmd
rabbitmq-plugins enable rabbitmq_management
rabbitmqctl status
```

Painel em <http://localhost:15672> (guest/guest -- o usuario `guest` so
autentica a partir do localhost, que e o caso aqui). Para parar e subir o
broker: `net stop RabbitMQ` / `net start RabbitMQ`.

### 3. Dependencias e chaves

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m tools.gen_keys

cd frontend; npm install; cd ..
```

### 4. Os processos

```powershell
.venv\Scripts\python -m ms_estoque.main
.venv\Scripts\python -m mock_pagamento.main
.venv\Scripts\python -m ms_pagamento.main
.venv\Scripts\python -m ms_entrega.main
.venv\Scripts\python -m ms_promocoes.main
.venv\Scripts\python -m ms_principal.main

cd frontend; npm run dev
```

Atalho (o `run_services.sh` e bash; no Windows use o `.ps1`):

```powershell
.\run_services.ps1 start     # sobe os 6 do backend em background (logs\)
.\run_services.ps1 logs
.\run_services.ps1 stop
cd frontend; npm run dev
```

Se o PowerShell bloquear o script por politica de execucao:
`powershell -ExecutionPolicy Bypass -File .\run_services.ps1 start`.

O script nao exige a venv dentro do projeto. Ele procura o interpretador nesta
ordem: `-Python <caminho>`, a variavel `PYTHON_EXE`, `.venv\Scripts\python.exe`,
a venv ativada (`VIRTUAL_ENV`) e, por ultimo, o `python.exe` do PATH. Antes de
subir qualquer processo ele testa `import pika, cryptography, fastapi, uvicorn,
httpx` no interpretador escolhido -- sem essa checagem, um Python errado subiria
os 6 processos, todos morreriam no import e o erro ficaria escondido nas janelas
ocultas. Para apontar para outra venv:

```powershell
.\run_services.ps1 start -Python C:\caminho\da\venv\Scripts\python.exe
```

Duas diferencas do script Windows, ambas por limitacao do `Start-Process`, que
nao aceita o mesmo arquivo para as duas saidas: o `logging` do Python escreve
em **stderr**, entao os eventos ficam em `logs\<servico>.log` e a saida solta
vai para `logs\<servico>.out.log`. E a checagem de PID confere tambem o nome do
processo, porque o Windows recicla PIDs rapido e um `stop` poderia derrubar
outro programa.

Variaveis de ambiente no PowerShell usam outra sintaxe:

```powershell
$env:INTERVALO_PROMOCAO="3"; .venv\Scripts\python -m ms_promocoes.main
```

### Problemas classicos no Windows

| Sintoma | Causa / solucao |
|---|---|
| Servico `RabbitMQ` nao inicia | Erlang instalado **depois** do RabbitMQ, ou fora do modo Administrador. Reinstale o RabbitMQ. |
| `rabbitmqctl` da erro de autenticacao (cookie) | O servico usa `C:\Windows\System32\config\systemprofile\.erlang.cookie` e a sua sessao usa `%USERPROFILE%\.erlang.cookie`. Copie o primeiro por cima do segundo e reinicie o servico. |
| Nome de usuario do Windows com acento ou espaco | O RabbitMQ engasga com o caminho do `%APPDATA%`. Defina `RABBITMQ_BASE=C:\RabbitMQ` nas variaveis de ambiente do sistema e reinstale o servico. |
| `[ERRO] Nao foi possivel conectar ao RabbitMQ` | A mensagem sugere `docker compose up -d`; aqui basta conferir `net start RabbitMQ`. |
| Porta 8000/8002/8003/8004 ocupada | Outro processo ja usa a porta. Troque pelas variaveis `GATEWAY_PORTA`, `PAGAMENTO_PORTA`, `MOCK_PORTA`. |

---
## Ferramentas de verificacao

```bash
.venv/bin/python -m tools.test_crypto                   # assina/verifica sem broker
.venv/bin/python -m tools.smoke_test P1 2 aprovado      # fluxo completo pela API
.venv/bin/python -m tools.smoke_test P6 1 recusado      # caminho da recusa
.venv/bin/python -m tools.smoke_test P3 1               # caminho do sem-estoque
.venv/bin/python -m tools.test_assinatura_invalida      # evento forjado e descartado
```

`test_crypto` roda 9 verificacoes de assinatura sem precisar do broker
(payload adulterado, evento trocado, timestamp remarcado, produtor falso,
produtor sem chave, envelope sem assinatura e round-trip JSON).

`smoke_test` faz o fluxo inteiro pela API REST, sem navegador: cria o pedido,
espera a `checkoutUrl` chegar e **simula o clique** no Mock pelo mesmo endpoint
que a pagina usa -- entao o caminho exercitado e exatamente o da demonstracao.
O terceiro argumento escolhe `aprovado` ou `recusado`.

`test_assinatura_invalida` publica quatro eventos -- legitimo, payload
adulterado, assinado com a chave de outro servico, e um evento substituido
(payload legitimo de `pedido.criado` republicado como `pagamento.aprovado`) --
e apenas o primeiro e processado. Bom roteiro para a pergunta "e se alguem
forjar um evento?". Exige `ms_estoque` e `ms_entrega` no ar.

Checagens rapidas de saude:

```bash
curl localhost:8000/health      # consumidor_vivo: a thread do pika ainda roda?
curl localhost:8002/produtos    # saldo persistido
curl -N localhost:8000/api/eventos/cli-demo   # acompanha o SSE no terminal
```

E o `GET /health` responde `consumidor_vivo` de proposito: sem ele, a thread do
consumidor poderia morrer e o processo seguir respondendo 200 em todas as rotas
sem processar evento nenhum.

### Tipagem

```bash
MYPYPATH=. mypy --explicit-package-bases --ignore-missing-imports \
    common tools ms_principal ms_estoque ms_pagamento ms_entrega \
    ms_promocoes mock_pagamento
cd frontend && npx tsc -b           # o frontend em strict mode
```

O `--explicit-package-bases` e necessario porque os servicos tem arquivos
`main.py` homonimos e o projeto nao usa `__init__.py`.

---
## Decisoes de projeto (o que defender)

### Seguranca e mensageria (herdado do Trab1, ainda valendo)

**1. A assinatura cobre `producer` + `event` + `timestamp` + `payload`**, nao
apenas o payload. Assinando so o payload, um atacante pega um envelope valido,
troca a routing key e o campo `event`, e reaproveita a assinatura: um payload
assinado para `pedido.criado` passa como `pagamento.aprovado` e o `ms_entrega`
emite nota fiscal de um pedido nunca pago. Ver
`tools/test_assinatura_invalida.py`, caso 4.

**2. Serializacao canonica (`canon`)**: `sort_keys=True` e sem espacos. Os
mesmos dados produzem sempre os mesmos bytes, no produtor e no consumidor.

**3. O hash e calculado explicitamente** (`sha256_digest`) e a assinatura usa
`utils.Prehashed`. Os tres passos do enunciado ficam separados no codigo:
gerar o hash, assinar com a privada, por no campo `signature`.

**4. A assinatura e verificada ANTES de processar**, em
`Microservice._ao_receber`. Assinatura invalida -> `basic_nack(requeue=False)`:
o evento e descartado e nunca chega ao `handle()`.

**5. A routing key da entrega tem de casar com o `event` assinado.** Um
envelope valido reencaminhado para outra fila e recusado.

**6. Excecao dentro do `handle()` tambem descarta o evento**, sem requeue. Com
requeue o mesmo evento voltaria em loop e travaria a fila.

**7. `prefetch_count=1`**: um evento por vez por consumidor. Alem da ordem
previsivel, e o que torna seguro bombear a conexao durante uma chamada HTTP
(item 13).

**8. Filas duraveis e mensagens persistentes** (`delivery_mode=2`).

**9. Idempotencia em todos os servicos com efeito colateral.** `ms_estoque`
nao reserva duas vezes, `ms_entrega` nao emite duas notas e -- novidade do
Trab2 -- o `ms_pagamento` nao publica dois resultados para o mesmo pedido.
Necessario porque a entrega do RabbitMQ e at-least-once, e porque **o usuario
pode clicar duas vezes no Mock**.

**10. O ID do pedido leva um sufixo de sessao** (`PED-A3F1-001`), para o
contador reiniciado nao colidir com o estado que os outros servicos mantem.

### REST, SSE e threads (o que o Trab2 trouxe)

**11. `pagamento.pendente` e um evento novo, fora da lista do enunciado.** A
URL de checkout nasce no `ms_pagamento` e precisa chegar ao navegador. O
`ms_pagamento` nao fala com o frontend, e o gateway e o unico que mantem SSE --
entao o unico caminho possivel e RabbitMQ -> gateway -> SSE. A alternativa
seria o `POST /api/pedidos` esperar a cadeia estoque->pagamento->mock de forma
sincrona, o que destruiria o modelo assincrono.

**12. Uma conexao pika por thread, e o publisher das rotas tem lock.** O
`BlockingConnection` nao e thread-safe. O consumidor tem a sua conexao; as
threads HTTP compartilham um `PublisherHTTP`, que serializa as publicacoes com
um `threading.Lock` -- cobrindo tambem a reconexao interna, que nao e
reentrante. O `acquire` tem prazo de 2s e vira HTTP 503: sem prazo, com o
broker fora, a thread presa no connect congelaria a API inteira atras dela.

**13. Chamada HTTP dentro do `handle()` bombeia a conexao.** O pika so
processa heartbeats quando o codigo esta dentro da biblioteca. Um `httpx.post`
direto no `handle()` seguraria a thread por segundos; o broker derrubaria a
conexao por timeout, o `basic_ack` seguinte estouraria e -- como a mensagem
nunca foi ackada -- ela voltaria por redelivery, **cobrando o cliente duas
vezes**. Por isso `Microservice.aguardar()` roda a chamada num executor e fica
em `process_data_events` ate ela terminar. So e seguro porque `prefetch_count=1`
garante que nao ha outra mensagem em voo para reentrar no `handle()`.

**14. O SSE e `async def` com `asyncio.Queue`, nunca gerador sincrono.** Um
gerador sincrono em `StreamingResponse` ocupa uma thread do pool do anyio (40
no total, compartilhadas com TODAS as rotas `def`) durante toda a conexao
aberta: 40 abas travariam a API inteira. Pior, um `queue.get()` bloqueado nao e
cancelavel, entao cada aba fechada vazaria uma thread para sempre. A thread do
pika entrega com `loop.call_soon_threadsafe`, e **o fan-out roda dentro do
loop** -- por isso o registro de assinantes nao precisa de lock.
Corolario: as rotas que **publicam** sao `def`, para irem ao threadpool. Uma
rota `async def` publicando bloquearia o loop e congelaria todos os SSE juntos.

**15. `confirm_delivery()` + `mandatory=True` no publisher das rotas.** Sem
confirms, `basic_publish` e fire-and-forget: a exchange `eCommerce` e direct,
e uma mensagem que nenhuma fila escuta e descartada pelo broker **sem erro
nenhum**. O `POST /api/pedidos` devolveria 202 para um pedido que nunca
existiria. Com confirms isso vira `UnroutableError` -> HTTP 503.

**16. `connect()` levanta excecao em vez de `sys.exit()`.** Esse foi o ponto
mais traicoeiro da migracao: `sys.exit` levanta `SystemExit`, e o modulo
`threading` trata `SystemExit` como **fim normal** da thread. Numa thread
secundaria, o processo nao morreria -- a thread do consumidor sumiria sem
traceback e o servidor HTTP seguiria respondendo 200 sem processar evento
algum. Hoje so os `if __name__ == "__main__"` traduzem a falha em `sys.exit`, e
o `GET /health` expoe `consumidor_vivo` justamente porque essa falha e
invisivel por definicao.

**17. Shutdown via `add_callback_threadsafe`.** E a unica API do
`BlockingConnection` chamavel de fora da thread dona. Alem disso: a thread do
consumidor e **non-daemon** com `join`, e o teardown poe uma sentinela em todas
as filas SSE -- um stream SSE nunca termina sozinho, e sem a sentinela o
graceful shutdown do uvicorn esperaria por ele para sempre.

**18. Um processo por servico, sem `--reload` e sem `--workers > 1`.** Cada
worker abriria o seu proprio consumidor na MESMA fila: o RabbitMQ distribuiria
os eventos em round-robin e o cliente conectado ao worker 2 perderia o evento
consumido pelo worker 1. O SSE quebraria de forma intermitente.

**19. O webhook exige segredo compartilhado.** Sem isso, qualquer um que
alcance a porta 8003 aprova qualquer pedido -- e o evento resultante sairia
**assinado pelo `ms_pagamento`**, fazendo toda a cadeia de assinatura do
trabalho atestar um dado forjado. A autenticidade do transporte interno nao
vale nada se a borda que alimenta esse transporte estiver aberta.

**20. SQLite em WAL, uma conexao por thread.** A thread do pika escreve
enquanto as threads HTTP leem o `GET /produtos`. WAL permite um escritor e N
leitores sem bloqueio. **Nao** usamos `check_same_thread=False`: isso faria as
threads compartilharem o estado de transacao, e uma leitura HTTP enxergaria a
transacao aberta pelo consumidor. A reserva de um pedido inteiro vai dentro de
`BEGIN IMMEDIATE`, mantendo o "tudo ou nada" que o Trab1 tinha de graca por ser
monothread.

**21. Transicao de estado atomica no `PedidoStore`.** `atualizar_se()` confere
o estado atual e grava sob o mesmo lock. Com varias threads HTTP, dois DELETE
concorrentes leriam o mesmo estado valido e publicariam dois `pedido.excluido`.

**22. Registrar o pedido ANTES de publicar.** O `pedido.estoque_ok` volta em
milissegundos e o `handle()` descarta evento de `pedidoId` desconhecido.
Publicar primeiro perderia o primeiro evento da cadeia. O instinto dentro de um
endpoint e publicar primeiro -- dai o comentario no codigo.

**23. O frontend abre o `EventSource` no mount**, antes de existir qualquer
pedido. Abrindo depois do POST, os primeiros eventos (que chegam em
milissegundos) se perderiam.

**24. O botao "Pagar agora" existe porque `window.open` costuma ser
bloqueado.** A abertura automatica da aba parte do callback do SSE, nao de um
clique do usuario, e o navegador barra. O botao visivel no card do pedido e a
garantia de que a demonstracao nunca trava.

**25. O `ms_promocoes` consome a propria promocao que publica.** Uma fila, dois
bindings, exchanges diferentes. Parece volta desnecessaria, mas separa geracao
de notificacao e preserva o topic exchange com curinga `*`, que era o que os
consumidores C1/C2 do Trab1 demonstravam. A fila tem `x-message-ttl` e
`x-max-length`: sendo duravel, o gerador parado por horas acumularia promocoes
velhas e viraria uma enxurrada de e-mails no restart.

**26. O `mock_pagamento` nao importa nada de `common/`.** Sem chave privada,
sem AMQP, sem envelope. E proposital: ele representa um sistema de terceiros,
que so conhece o `ms_pagamento` por HTTP. Se ele compartilhasse o codigo de
assinatura, a fronteira "externo" deixaria de significar alguma coisa.

**27. As routing keys da exchange `eCommerce` vivem em um `StrEnum`**
(`common/eventos.py`). Um erro de digitacao ali e um bug silencioso: o evento
sai numa chave que nenhuma fila escuta e nada estoura -- o pedido so para de
andar. Como `StrEnum` herda de `str`, o membro serve direto como routing key do
pika e como valor do campo `event`. As chaves de **promocao** ficam de fora: a
do produtor e montada em tempo de execucao
(`f"promocao.categoria.{categoria}"`) e a do consumidor e um padrao de binding
com curinga -- nenhuma das duas e um valor fixo que caiba num enum fechado.

**28. O `Status` carrega o rotulo exibido**, em vez de um dicionario paralelo
que podia sair de sincronia. O valor do membro continua sendo o nome interno,
e o `startswith("CANCELADO")` segue funcionando.

**29. O catalogo (`common/catalogo.py`) continua local, mas o SALDO agora e
consultado.** No Trab1 o saldo era invisivel fora do `ms_estoque`, porque
qualquer consulta exigiria chamada direta entre processos -- proibida. O Trab2
autoriza explicitamente o gateway a consultar o `ms_estoque` via REST, entao a
tela mostra o estoque real. O `catalogo.py` segue sendo so a tabela cadastral,
carregada localmente como um arquivo de configuracao, e e a semente do banco.

---

## Limitacoes conhecidas

- **A exclusao pelo usuario nao e coordenada com o pagamento.** A tela recusa
  excluir um pedido ja `ENVIADO` ou ja cancelado, mas aceita excluir um pedido
  com pagamento aprovado: o `pedido.excluido` devolve a reserva no estoque e
  nao existe evento de estorno, entao o pedido fica "cancelado, mas pago".
- **Eventos que chegam depois do cancelamento sobrescrevem o status.** Se o
  usuario excluir e um `pagamento.aprovado` ja estiver a caminho, o status
  exibido deixa de ser "CANCELADO".
- **O `PedidoStore` do gateway vive em RAM**: reiniciar o gateway zera a lista
  de pedidos (o enunciado so exige persistencia no `ms_estoque`). O estoque e
  as reservas, esses, sobrevivem.
- **O `ms_entrega` guarda as notas emitidas em RAM**: reiniciar permite emitir
  nota duplicada para um `pagamento.aprovado` reentregue.
- **O publisher das rotas e um so, com lock.** Sob carga real, o caminho mais
  robusto seria uma thread publicadora dedicada com fila e `Future` por
  publicacao -- elimina o lock e permite voltar a usar heartbeat. Para a escala
  deste trabalho, o lock com prazo resolve e e muito mais simples de defender.

## Observacoes

- As chaves **privadas** (`*.key.pem`, permissao 0600) estao no `.gitignore`.
  As **publicas** (`*.pub.pem`) sao versionadas, como pede a especificacao.
- O `.env` esta no `.gitignore`; o `.env.example` e versionado, sem valores.
- O banco `ms_estoque/estoque.db` e o `ms_promocoes/interesses.json` sao
  estado local e tambem ficam fora do git.
- Requer **Python 3.12 ou superior**: `StrEnum` (3.11), `match` (3.10),
  `typing.override` e `typing.Self` (3.12/3.11). Testado com Python 3.13.15,
  pika 1.3.2, cryptography 43.0.3, FastAPI 0.115, RabbitMQ 3.13 e Node 24.
- O `@override` nos `handle()` so e verificado por type checker estatico, nao
  em tempo de execucao.
