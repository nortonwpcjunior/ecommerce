# E-commerce distribuido com RabbitMQ

Trabalho de Sistemas Distribuidos (UTFPR / Profa. Ana Cristina Kochem Vendramin).
Backend de e-commerce em microsservicos, com arquitetura orientada a eventos e
assinatura digital (RSA-2048). Nenhum processo chama outro diretamente: toda a
comunicacao passa pelo RabbitMQ.

Este README traz apenas o necessario para executar o projeto.

---

## Pre-requisitos

- **Python 3.12 ou superior** (usa `StrEnum`, `match` e `typing.override`).
  Testado com Python 3.14.7 e 3.13.15.
- **RabbitMQ 3.13** -- via Docker (Linux/macOS) ou instalacao nativa (Windows).
- Dependencias Python: `pika==1.3.2` e `cryptography==43.0.3`
  (em `requirements.txt`).

## Os 7 processos

Sao 7 processos independentes. Apenas o `ms_principal` e interativo: ele tem o
menu do usuario. Os outros 6 rodam em silencio, escrevendo nos logs.

| Processo | Papel |
|---|---|
| `ms_principal` | **Menu do usuario** (criar, consultar e excluir pedidos) |
| `ms_estoque` | Reserva e devolve itens do estoque |
| `ms_pagamento` | Aprova ou recusa o pagamento |
| `ms_entrega` | Emite a nota e envia o pedido |
| `ms_promocoes` | Publica promocoes por categoria, periodicamente |
| `consumidor_c1` | Assina promocoes das categorias A e B |
| `consumidor_c2` | Assina promocoes de todas as categorias (curinga) |

---

## Como rodar (Linux / macOS)

### 1. Subir o broker

```bash
docker compose up -d          # RabbitMQ em localhost:5672
                              # painel: http://localhost:15672 (guest/guest)
```

### 2. Instalar dependencias e gerar as chaves

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tools.gen_keys        # gera os 5 pares RSA-2048
```

`gen_keys` coloca, em cada `<servico>/keys/`, a chave privada do servico e as
chaves publicas de todos os microsservicos. As chaves publicas ja vem no zip;
o passo acima gera as **privadas**, necessarias para assinar os eventos. Rodar
de novo nao sobrescreve o que existe -- use `--force` se quiser novas chaves.

### 3. Subir os 7 processos

Cada comando em **um terminal separado** (deixa visivel que sao processos
independentes). Suba o `ms_principal` por ultimo:

```bash
.venv/bin/python -m ms_estoque.main
.venv/bin/python -m ms_pagamento.main
.venv/bin/python -m ms_entrega.main
.venv/bin/python -m ms_promocoes.main
.venv/bin/python -m consumidor_c1.main
.venv/bin/python -m consumidor_c2.main
.venv/bin/python -m ms_principal.main      # este e a interface
```

Alternativa com um unico terminal -- o script sobe os 6 processos
nao-interativos em background e grava a saida em `logs/`:

```bash
./run_services.sh start
./run_services.sh logs       # acompanha os logs de todos
.venv/bin/python -m ms_principal.main
./run_services.sh stop       # ao terminar
```

Se o zip tiver perdido a permissao de execucao do script, use
`bash run_services.sh start` ou rode `chmod +x run_services.sh` antes.

---

## Como rodar no Windows (RabbitMQ nativo, sem Docker)

O Docker so e usado para subir o broker. No Windows da para instalar o RabbitMQ
nativo e o resto do projeto nao muda: os processos continuam falando com
`localhost:5672`.

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

### 3. Instalar dependencias e gerar as chaves

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m tools.gen_keys
```

### 4. Subir os 7 processos

```powershell
.venv\Scripts\python -m ms_estoque.main
.venv\Scripts\python -m ms_pagamento.main
.venv\Scripts\python -m ms_entrega.main
.venv\Scripts\python -m ms_promocoes.main
.venv\Scripts\python -m consumidor_c1.main
.venv\Scripts\python -m consumidor_c2.main
.venv\Scripts\python -m ms_principal.main      # este e a interface
```

Alternativa com um unico terminal (o `run_services.sh` e bash; no Windows use
o `.ps1`):

```powershell
.\run_services.ps1 start     # sobe os 6 nao-interativos em background (logs\)
.\run_services.ps1 logs      # acompanha os logs de todos
.venv\Scripts\python -m ms_principal.main
.\run_services.ps1 stop      # ao terminar
```

Se o PowerShell bloquear o script por politica de execucao:
`powershell -ExecutionPolicy Bypass -File .\run_services.ps1 start`.

O script nao exige a venv dentro do projeto. Ele procura o interpretador nesta
ordem: `-Python <caminho>`, a variavel `PYTHON_EXE`, `.venv\Scripts\python.exe`,
a venv ativada (`VIRTUAL_ENV`) e, por ultimo, o `python.exe` do PATH. Para
apontar para outra venv:

```powershell
.\run_services.ps1 start -Python C:\caminho\da\venv\Scripts\python.exe
```

No Windows os eventos ficam em `logs\<servico>.log` e a saida solta vai para
`logs\<servico>.out.log` (o `logging` do Python escreve em stderr, e o
`Start-Process` nao aceita o mesmo arquivo para as duas saidas).

### Problemas classicos no Windows

| Sintoma | Causa / solucao |
|---|---|
| Servico `RabbitMQ` nao inicia | Erlang instalado **depois** do RabbitMQ, ou fora do modo Administrador. Reinstale o RabbitMQ. |
| `rabbitmqctl` da erro de autenticacao (cookie) | O servico usa `C:\Windows\System32\config\systemprofile\.erlang.cookie` e a sua sessao usa `%USERPROFILE%\.erlang.cookie`. Copie o primeiro por cima do segundo e reinicie o servico. |
| Nome de usuario do Windows com acento ou espaco | O RabbitMQ engasga com o caminho do `%APPDATA%`. Defina `RABBITMQ_BASE=C:\RabbitMQ` nas variaveis de ambiente do sistema e reinstale o servico. |
| `[ERRO] Nao foi possivel conectar ao RabbitMQ` | A mensagem sugere `docker compose up -d`; aqui basta conferir `net start RabbitMQ`. |

---

## Variaveis de ambiente

| Variavel | Padrao | Efeito |
|---|---|---|
| `TAXA_APROVACAO` | `0.7` | chance de o pagamento ser aprovado; `0` forca recusa, `1` forca aprovacao |
| `INTERVALO_PROMOCAO` | `8` | segundos entre promocoes |
| `RABBIT_HOST` / `RABBIT_PORT` | `localhost` / `5672` | endereco do broker |
| `RABBIT_USER` / `RABBIT_PASS` | `guest` / `guest` | credenciais do broker |

Para forcar a recusa de pagamento:

```bash
TAXA_APROVACAO=0 .venv/bin/python -m ms_pagamento.main               # Linux/macOS
```

```powershell
$env:TAXA_APROVACAO="0"; .venv\Scripts\python -m ms_pagamento.main   # Windows
```

## Notas de execucao

- **Estoque inicial** (em `ms_estoque/main.py`): `P1=10 P2=5 P3=0 P4=3 P5=7
  P6=2`. O `P3` comeca zerado de proposito -- e o caminho mais rapido para ver
  o evento `estoque.indisponivel`.
- O fluxo completo, de `pedido.criado` ate `pedido.enviado`, termina em cerca
  de 15 ms. Os estados intermediarios (`ESTOQUE_RESERVADO`,
  `PAGAMENTO_APROVADO`) aparecem nos logs, mas em "Consultar meus pedidos" o
  pedido geralmente ja aparece em `ENVIADO`.
- Para acompanhar a cadeia de eventos, veja os logs dos processos: cada
  publicacao e cada consumo aparecem com horario, produtor e hash.
- No menu, os eventos chegam em outra thread e imprimem no console. Se a tela
  embolar durante uma digitacao, ENTER redesenha o menu.
- O estado dos servicos vive em RAM: reiniciar um processo zera pedidos,
  reservas e notas emitidas.
