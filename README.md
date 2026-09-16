# E-commerce distribuido com RabbitMQ

Trabalho de Sistemas Distribuidos (UTFPR / Profa. Ana Cristina Kochem Vendramin).
Backend de e-commerce em **microsservicos**, **arquitetura orientada a eventos** e
**assinatura digital com criptografia assimetrica**.

Nenhum processo chama outro diretamente: toda a comunicacao passa pelo RabbitMQ.

---

## Processos

| Processo | Fila propria | Consome | Publica |
|---|---|---|---|
| `ms_principal` | `fila.principal` | `pedido.estoque_ok`, `estoque.indisponivel`, `pagamento.aprovado`, `pagamento.recusado`, `pedido.enviado` | `pedido.criado`, `pedido.excluido` |
| `ms_estoque` | `fila.estoque` | `pedido.criado`, `pedido.excluido` | `pedido.estoque_ok`, `estoque.indisponivel` |
| `ms_pagamento` | `fila.pagamento` | `pedido.estoque_ok` | `pagamento.aprovado`, `pagamento.recusado` |
| `ms_entrega` | `fila.entrega` | `pagamento.aprovado` | `pedido.enviado` |
| `ms_promocoes` | — | — | `promocao.categoria.{A,B,C}` |
| `consumidor_c1` | `fila.C1` | `promocao.categoria.A`, `promocao.categoria.B` | — |
| `consumidor_c2` | `fila.C2` | `promocao.categoria.*` | — |

Exchanges: **`eCommerce`** (direct) e **`Promocoes`** (topic). Nenhuma fanout.
Cada consumidor declara a SUA fila (`durable=True`) e faz os proprios bindings.

C1 usa dois bindings exatos (`promocao.categoria.A` e `.B`); C2 usa um unico
binding com curinga `*`, que casa exatamente uma palavra e portanto cobre
qualquer categoria, inclusive as que venham a existir.

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
│   ├── eventos.py        # Evento (StrEnum): fonte unica das routing keys
│   ├── envelope.py       # Envelope + serializacao canonica (canon)
│   ├── crypto.py         # hash, assinatura, verificacao, chaves
│   ├── service.py        # conexao, topologia, Publisher, Microservice
│   ├── promocao.py       # base dos consumidores C1/C2 (publica=False)
│   └── catalogo.py       # dados cadastrais dos produtos (sem estoque)
├── tools/
│   ├── gen_keys.py       # gera os 5 pares e distribui as publicas
│   ├── test_crypto.py    # 9 verificacoes de assinatura, sem broker
│   ├── smoke_test.py     # fluxo ponta a ponta, sem menu
│   └── test_assinatura_invalida.py
├── ms_principal/         # menu do usuario + consumidor (2 threads)
│   ├── main.py
│   └── keys/             # ms_principal.key.pem + *.pub.pem dos demais
├── ms_estoque/           ...
├── ms_pagamento/         ...
├── ms_entrega/           ...
├── ms_promocoes/         ...
├── consumidor_c1/        # so keys/ms_promocoes.pub.pem (nao publica)
├── consumidor_c2/
├── run_services.sh       # atalho bash (Linux/macOS)
├── run_services.ps1      # atalho Windows (PowerShell)
└── docker-compose.yml
```

## Fluxo dos eventos

```
        usuario
           |  (menu no terminal)
      ms_principal ---- pedido.criado -----------> ms_estoque
           |                                            |
           |<--------- pedido.estoque_ok ---------------|  (reserva os itens)
           |<--------- estoque.indisponivel ------------|
           |                                            ^
           |--------- pedido.excluido ------------------'  (devolve a reserva)
           |
           |            ms_estoque -- pedido.estoque_ok --> ms_pagamento
           |<--------- pagamento.aprovado --------------------|
           |<--------- pagamento.recusado --------------------|
           |
           |         ms_pagamento -- pagamento.aprovado --> ms_entrega
           |<--------- pedido.enviado ------------------------|

    ms_promocoes -- promocao.categoria.X --> [C1: A e B]  [C2: *]
```

O `pedido.excluido` sai em tres situacoes: o usuario exclui pelo menu, o
`ms_estoque` avisa `estoque.indisponivel`, ou o `ms_pagamento` recusa. Nos dois
ultimos casos quem publica e o `ms_principal`, ao consumir o evento.

---

## Como rodar (Linux / macOS)

### 1. Broker

```bash
docker compose up -d          # RabbitMQ em localhost:5672
                              # painel: http://localhost:15672 (guest/guest)
```

Para apontar para outro endereco/porta: `RABBIT_HOST`, `RABBIT_PORT`,
`RABBIT_USER`, `RABBIT_PASS`.

### 2. Dependencias e chaves

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tools.gen_keys        # gera os 5 pares RSA-2048
```

`gen_keys` coloca, em cada `<servico>/keys/`, a chave privada do servico e as
chaves publicas de **todos** os microsservicos. C1 e C2 recebem apenas a publica
do `ms_promocoes` (nao publicam nada). Rodar de novo nao sobrescreve: use
`--force` se quiser novas chaves.

### 3. Os 7 processos

**Para a defesa, use 7 terminais** (torna visivel que sao processos independentes):

```bash
.venv/bin/python -m ms_estoque.main
.venv/bin/python -m ms_pagamento.main
.venv/bin/python -m ms_entrega.main
.venv/bin/python -m ms_promocoes.main
.venv/bin/python -m consumidor_c1.main
.venv/bin/python -m consumidor_c2.main
.venv/bin/python -m ms_principal.main      # este e a interface
```

Atalho durante o desenvolvimento:

```bash
./run_services.sh start      # sobe os 6 nao-interativos em background (logs/)
./run_services.sh logs       # acompanha todos os logs
./run_services.sh stop
.venv/bin/python -m ms_principal.main
```

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
```

### 4. Os 7 processos

```powershell
.venv\Scripts\python -m ms_estoque.main
.venv\Scripts\python -m ms_pagamento.main
.venv\Scripts\python -m ms_entrega.main
.venv\Scripts\python -m ms_promocoes.main
.venv\Scripts\python -m consumidor_c1.main
.venv\Scripts\python -m consumidor_c2.main
.venv\Scripts\python -m ms_principal.main      # este e a interface
```

Atalho (o `run_services.sh` e bash; no Windows use o `.ps1`):

```powershell
.\run_services.ps1 start     # sobe os 6 nao-interativos em background (logs\)
.\run_services.ps1 logs      # acompanha todos os logs
.\run_services.ps1 stop
.venv\Scripts\python -m ms_principal.main
```

Se o PowerShell bloquear o script por politica de execucao:
`powershell -ExecutionPolicy Bypass -File .\run_services.ps1 start`.

O script nao exige a venv dentro do projeto. Ele procura o interpretador nesta
ordem: `-Python <caminho>`, a variavel `PYTHON_EXE`, `.venv\Scripts\python.exe`,
a venv ativada (`VIRTUAL_ENV`) e, por ultimo, o `python.exe` do PATH. Antes de
subir qualquer processo ele testa `import pika, cryptography` no interpretador
escolhido -- sem essa checagem, um Python errado subiria os 6 processos, todos
morreriam no import e o erro ficaria escondido nas janelas ocultas. Para apontar
para outra venv:

```powershell
.\run_services.ps1 start -Python C:\caminho\da\venv\Scripts\python.exe
```

Duas diferencas do script Windows, ambas por limitacao do `Start-Process`, que
nao aceita o mesmo arquivo para as duas saidas: o `logging` do Python escreve
em **stderr**, entao os eventos ficam em `logs\<servico>.log` e a saida solta
vai para `logs\<servico>.out.log`. E a checagem de PID confere tambem o nome do
processo, porque o Windows recicla PIDs rapido e um `stop` poderia derrubar
outro programa.

Variaveis de ambiente no PowerShell usam outra sintaxe. Para forcar recusa de
pagamento na demonstracao:

```powershell
$env:TAXA_APROVACAO="0"; .venv\Scripts\python -m ms_pagamento.main
```

O mesmo vale para `INTERVALO_PROMOCAO`, `RABBIT_HOST`, `RABBIT_PORT`,
`RABBIT_USER` e `RABBIT_PASS`.

### Problemas classicos no Windows

| Sintoma | Causa / solucao |
|---|---|
| Servico `RabbitMQ` nao inicia | Erlang instalado **depois** do RabbitMQ, ou fora do modo Administrador. Reinstale o RabbitMQ. |
| `rabbitmqctl` da erro de autenticacao (cookie) | O servico usa `C:\Windows\System32\config\systemprofile\.erlang.cookie` e a sua sessao usa `%USERPROFILE%\.erlang.cookie`. Copie o primeiro por cima do segundo e reinicie o servico. |
| Nome de usuario do Windows com acento ou espaco | O RabbitMQ engasga com o caminho do `%APPDATA%`. Defina `RABBITMQ_BASE=C:\RabbitMQ` nas variaveis de ambiente do sistema e reinstale o servico. |
| `[ERRO] Nao foi possivel conectar ao RabbitMQ` | A mensagem sugere `docker compose up -d`; aqui basta conferir `net start RabbitMQ`. |

---

## Ferramentas de verificacao

```bash
.venv/bin/python -m tools.test_crypto              # assina/verifica sem broker
.venv/bin/python -m tools.smoke_test P1 2          # fluxo ponta a ponta, sem menu
.venv/bin/python -m tools.test_assinatura_invalida # prova que evento forjado e descartado
```

`test_crypto` roda 9 verificacoes de assinatura sem precisar do broker
(payload adulterado, evento trocado, timestamp remarcado, produtor falso,
produtor sem chave, envelope sem assinatura e round-trip JSON).

`test_assinatura_invalida` publica quatro eventos -- legitimo, payload
adulterado, assinado com a chave de outro servico, e um evento substituido
(payload legitimo de `pedido.estoque_ok` republicado como
`pagamento.aprovado`) -- e apenas o primeiro e processado. Bom roteiro para a
pergunta "e se alguem forjar um evento?". Exige `ms_estoque` e `ms_entrega` no ar.

`smoke_test` sobe um consumidor `ms_principal` embutido, publica um
`pedido.criado` e espera o status chegar a um estado terminal (`ENVIADO`,
`CANCELADO_SEM_ESTOQUE` ou `CANCELADO_PAGAMENTO`), com timeout de 30s.

### Variaveis de simulacao

| Variavel | Padrao | Efeito |
|---|---|---|
| `TAXA_APROVACAO` | `0.7` | chance de o pagamento ser aprovado; `0` forca recusa, `1` forca aprovacao |
| `INTERVALO_PROMOCAO` | `8` | segundos entre promocoes |
| `RABBIT_HOST` / `RABBIT_PORT` | `localhost` / `5672` | endereco do broker |
| `RABBIT_USER` / `RABBIT_PASS` | `guest` / `guest` | credenciais do broker |

A latencia do pagamento e da emissao da nota e fixa (`time.sleep(1)` em
`ms_pagamento` e `ms_entrega`), o suficiente para os estados intermediarios
aparecerem no menu durante a demonstracao.

Estoque inicial (em `ms_estoque/main.py`): `P1=10 P2=5 P3=0 P4=3 P5=7 P6=2`.
O `P3` comeca zerado de proposito -- e o caminho mais rapido para demonstrar
`estoque.indisponivel`.

---

## Decisoes de projeto (o que defender)

**1. A assinatura cobre `producer` + `event` + `timestamp` + `payload`**, nao
apenas o payload. Assinando so o payload, um atacante pega um envelope valido,
troca a routing key e o campo `event`, e reaproveita a assinatura: um payload
assinado para `pedido.estoque_ok` passa como `pagamento.aprovado` e o
`ms_entrega` emite nota fiscal de um pedido nunca pago. Ver
`tools/test_assinatura_invalida.py`, caso 4.

**2. Serializacao canonica (`canon`)**: `sort_keys=True` e sem espacos. Os
mesmos dados produzem sempre os mesmos bytes, no produtor e no consumidor.

**3. O hash e calculado explicitamente** (`sha256_digest`) e a assinatura usa
`utils.Prehashed`. Os tres passos do enunciado ficam separados no codigo:
gerar o hash, assinar com a privada, por no campo `signature`. O hash aparece
tambem nos logs de publicacao, para conferencia na demonstracao.

**4. A assinatura e verificada ANTES de processar**, em
`Microservice._ao_receber`. Assinatura invalida -> `basic_nack(requeue=False)`:
o evento e descartado e nunca chega ao `handle()`. O mesmo vale para corpo que
nao e JSON valido ou envelope sem os campos obrigatorios.

**5. A routing key da entrega tem de casar com o `event` assinado.** Defesa
extra: um envelope valido reencaminhado para outra fila e recusado.

**6. Excecao dentro do `handle()` tambem descarta o evento**, sem requeue. Com
requeue o mesmo evento voltaria em loop e travaria a fila -- o erro fica no log
(`log.exception`) e a fila segue andando.

**7. `heartbeat=0` na conexao de publicacao.** O pika so processa heartbeats
quando o codigo chama a biblioteca, e a thread do menu fica parada em
`input()`. Com heartbeat ligado, o broker derruba a conexao por timeout e o
proximo pedido falha com `StreamLostError` -- acontece em ~2 minutos de menu
aberto. A conexao do consumidor mantem `heartbeat=60`, porque ela nunca fica
ociosa dentro da biblioteca.

**8. O `Publisher` reconecta** se a conexao propria cair. Quando o canal e
emprestado do consumidor, a excecao sobe: quem reconecta e o dono do canal.

**9. O `ms_principal` usa DUAS conexoes.** O `BlockingConnection` do pika nao e
thread-safe. A thread do consumidor usa a conexao de `Microservice`; a thread
do menu usa um `Publisher` com conexao propria. E publicar sempre FORA do
lock, para nao prender a thread do menu durante a ida ao broker.

**10. `prefetch_count=1`**: um evento por vez por consumidor, ordem de
processamento previsivel. E a razao de o `ms_estoque` nao precisar de `Lock`:
os handlers nunca rodam em paralelo la.

**11. Filas duraveis e mensagens persistentes** (`delivery_mode=2`): derrubar
um microsservico nao perde eventos, ele reprocessa ao voltar.

**12. O ID do pedido leva um sufixo de sessao** (`PED-A3F1-001`). Sem isso,
reiniciar o `ms_principal` reinicia o contador em 1 e os IDs colidem com o
estado que `ms_estoque` e `ms_pagamento` ainda mantem em memoria.

**13. Evento para pedido desconhecido e registrado e ignorado.** O
`ms_principal` e a unica origem de pedidos; um `pedidoId` que ele nao criou
nunca vira um pedido na lista do usuario.

**14. Idempotencia no `ms_estoque` e no `ms_entrega`**: `pedido.criado`
repetido nao reserva duas vezes, `pagamento.aprovado` repetido nao emite duas
notas. Necessario porque a entrega do RabbitMQ e at-least-once.

**15. As quantidades em estoque vivem APENAS no `ms_estoque`.**
`common/catalogo.py` tem so os dados cadastrais do produto -- e uma tabela de
referencia carregada localmente, como um arquivo de configuracao, nao uma
chamada entre processos. Por isso o menu nao mostra saldo: nao ha como
consultar sem chamada direta, que o enunciado proibe.

**16. Consumidores de promocoes usam `publica=False`** e nao tem chave
privada. Nao podem publicar nada nem falar com microsservico algum, so com o
broker.

**17. As routing keys vivem em um `StrEnum`** (`common/eventos.py`). Antes
cada nome aparecia como string literal solta em varios arquivos
(`pedido.criado` 13 vezes, `pedido.estoque_ok` e `pagamento.aprovado` 8 cada).
Um erro de digitacao ali e um bug silencioso: o evento sai numa chave que
nenhuma fila escuta, ou um binding nunca casa, e nada estoura -- o pedido so
para de andar. Como `StrEnum` herda de `str`, o membro serve direto como
routing key do pika e como valor do campo `event`: a serializacao canonica
produz os mesmos bytes e a assinatura nao muda (o hash do `tools.test_crypto`
e o mesmo de antes da mudanca).

**18. O `Status` carrega o rotulo exibido** em vez de existir um dicionario
`STATUS` paralelo, que podia sair de sincronia com os status usados no codigo.
O valor do membro continua sendo o nome interno, entao o
`startswith("CANCELADO")` do menu segue funcionando.

**19. O despacho de eventos usa `match`** no `ms_principal` (5 casos) e no
`ms_estoque`. Atencao ao escrever: `case Evento.PEDIDO_CRIADO` e padrao de
VALOR porque o nome e pontilhado; um `case PEDIDO_CRIADO` solto seria padrao
de CAPTURA e casaria com qualquer evento.

## Limitacoes conhecidas

- **A exclusao pelo usuario nao e coordenada com o pagamento.** O menu recusa
  excluir um pedido ja `ENVIADO` ou ja cancelado, mas aceita excluir um pedido
  com pagamento aprovado: o `pedido.excluido` devolve a reserva no estoque e
  nao existe evento de estorno, entao o pedido fica "cancelado, mas pago".
- **Eventos que chegam depois do cancelamento sobrescrevem o status.** Se o
  usuario excluir e um `pagamento.aprovado` ou `pedido.enviado` ja estiver a
  caminho, o status exibido deixa de ser "CANCELADO".
- O estado dos tres servicos com memoria (`ms_principal`, `ms_estoque`,
  `ms_entrega`) vive em RAM: reiniciar o processo zera pedidos, reservas e
  notas emitidas.

## Observacoes

- As chaves **privadas** (`*.key.pem`, permissao 0600) estao no `.gitignore`.
  As **publicas** (`*.pub.pem`) sao versionadas, como pede a especificacao.
- Ao rodar o menu, os eventos chegam em outra thread e imprimem no console.
  Se a tela embolar durante uma digitacao, ENTER redesenha o menu.
- Requer **Python 3.12 ou superior**: `StrEnum` (3.11), `match` (3.10),
  `typing.override` e `typing.Self` (3.12/3.11). Testado com Python 3.14.7 e
  3.13.15, pika 1.3.2, cryptography 43.0.3, RabbitMQ 3.13. O
  `cryptography 43.0.3` instala no 3.14 pelo wheel `cp39-abi3`, sem compilar.
- O `@override` nos `handle()` so e verificado por type checker estatico, nao
  em tempo de execucao. Para que ele pegue um `handle` escrito errado:

  ```bash
  MYPYPATH=. mypy --explicit-package-bases --ignore-missing-imports \
      common tools ms_principal ms_estoque ms_pagamento ms_entrega \
      ms_promocoes consumidor_c1 consumidor_c2
  ```

  O `--explicit-package-bases` e necessario porque os servicos tem arquivos
  `main.py` homonimos e o projeto nao usa `__init__.py`.
