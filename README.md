# E-commerce distribuido: microsservicos, REST, SSE e RabbitMQ

Trabalho 2 de Sistemas Distribuidos (UTFPR / Profa. Ana Cristina Barreiras Kochem Vendramin).

Evolucao do e-commerce do Trab1 para uma aplicacao Web completa: **frontend
React** (TypeScript), **API Gateway REST** com notificacoes **SSE**,
microsservicos Python que conversam **apenas pelo RabbitMQ**, **Mock de
Pagamento** externo com **webhook**, envio de e-mail pela **API do Resend** e
**assinatura digital RSA** em todas as mensagens do broker.

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

Nenhum microsservico de negocio chama outro diretamente. O HTTP aparece so nas
fronteiras previstas no enunciado: frontend <-> gateway, gateway -> `GET
/produtos` do estoque, `ms_pagamento` <-> Mock (cobranca + webhook) e
`ms_promocoes` -> Resend.

| Processo | Porta | Consome | Publica |
|---|---|---|---|
| `ms_principal` (gateway) | 8000 | `pedido.estoque_ok`, `estoque.indisponivel`, `pagamento.pendente`, `pagamento.aprovado`, `pagamento.recusado`, `pedido.enviado` | `pedido.criado`, `pedido.excluido`, `interesse.promocao` |
| `ms_estoque` | 8002 | `pedido.criado`, `pedido.excluido` | `pedido.estoque_ok`, `estoque.indisponivel` |
| `ms_pagamento` | 8003 | `pedido.estoque_ok`, `pedido.excluido` | `pagamento.pendente`, `pagamento.aprovado`, `pagamento.recusado` |
| `ms_entrega` | — | `pagamento.aprovado` | `pedido.enviado` |
| `ms_promocoes` | — | `interesse.promocao`, `promocao.categoria.*` | `promocao.categoria.{A,B,C}` |
| `mock_pagamento` | 8004 | — (sistema externo, nao usa AMQP) | — |
| `frontend` | 5173 | SSE do gateway | REST para o gateway |

Exchanges: `eCommerce` (direct) e `Promocoes` (topic). Cada consumidor declara
a propria fila duravel.

`pagamento.pendente` e um evento extra: leva a URL de checkout gerada pelo
Mock ate o gateway, que a repassa ao navegador pelo SSE para abrir a aba de
pagamento.

## Endpoints REST do gateway

Documentacao interativa: <http://localhost:8000/docs>.

| Metodo | Rota | O que faz |
|---|---|---|
| `GET` | `/api/produtos` | lista produtos com saldo, consultando o `ms_estoque` via REST |
| `POST` | `/api/pedidos` | cria o pedido e publica `pedido.criado` |
| `GET` | `/api/pedidos?clienteId=` | pedidos do cliente |
| `DELETE` | `/api/pedidos/{id}` | publica `pedido.excluido` (permitido ate o pagamento ser aprovado) |
| `POST` | `/api/interesses` | registra interesse em categorias (`interesse.promocao`) |
| `DELETE` | `/api/interesses?email=` | cancela o interesse (`interesse.promocao`) |
| `GET` | `/api/categorias` | categorias disponiveis |
| `GET` | `/api/eventos/{clienteId}` | **SSE** com toda mudanca de estado dos pedidos do cliente |

Outros endpoints: `GET /produtos` (estoque), `POST /webhook/pagamento`
(pagamento), `POST /cobrancas` e `GET /checkout/{id}` (Mock).

## Fluxo de um pedido

1. O frontend faz `POST /api/pedidos`; o gateway publica `pedido.criado`.
2. O `ms_estoque` reserva os itens e publica `pedido.estoque_ok` (ou
   `estoque.indisponivel`).
3. O `ms_pagamento` cria a cobranca no Mock, informando sua URL de webhook, e
   publica `pagamento.pendente` com a URL de checkout.
4. O navegador recebe a URL pelo SSE e abre o Mock em nova aba (ou pelo botao
   "Pagar agora").
5. O usuario clica em "Pagamento Aprovado" ou "Pagamento Recusado"; o Mock
   chama o webhook e o `ms_pagamento` publica `pagamento.aprovado` ou
   `pagamento.recusado`.
6. Se aprovado, o `ms_entrega` emite a nota fiscal e publica `pedido.enviado`.

Cada transicao chega ao navegador pelo SSE. Estoque indisponivel ou pagamento
recusado fazem o gateway publicar `pedido.excluido`, que devolve a reserva ao
estoque.

## Assinatura digital

Todo evento trafega neste envelope:

```json
{
  "producer":  "ms_estoque",
  "event":     "pedido.estoque_ok",
  "timestamp": "2026-09-11T13:04:55+00:00",
  "payload":   { "pedidoId": "PED-A3F1-001", "itens": [], "total": 0.0 },
  "signature": "<base64>"
}
```

- O produtor calcula o SHA-256 da serializacao canonica de `producer`,
  `event`, `timestamp` e `payload` e assina com sua chave privada RSA-2048.
- O consumidor verifica a assinatura com a chave publica do produtor **antes**
  de processar; assinatura invalida faz o evento ser descartado.
- Assinar o envelope inteiro (e nao so o payload) impede reaproveitar uma
  assinatura valida trocando o tipo do evento.
- O webhook do Mock exige um segredo compartilhado, para que ninguem aprove
  pagamentos chamando a porta 8003 diretamente.

---

## Como rodar

Requisitos: Python 3.12+, Node 20+ e RabbitMQ (via Docker ou instalado
localmente).

### 1. Broker

```bash
docker compose up -d     # RabbitMQ em localhost:5672, painel em http://localhost:15672 (guest/guest)
```

No Windows sem Docker, instale o Erlang/OTP e o RabbitMQ Server como
Administrador; o servico `RabbitMQ` passa a escutar em `localhost:5672`.

### 2. Dependencias e chaves

Linux / macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tools.gen_keys        # gera os 5 pares RSA e distribui as chaves publicas
cd frontend && npm install && cd ..
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m tools.gen_keys
cd frontend; npm install; cd ..
```

### 3. Configuracao

Copie `.env.example` para `.env`. Os valores padrao ja funcionam localmente.

| Variavel | Padrao | Efeito |
|---|---|---|
| `RESEND_API_KEY` | *(vazio)* | sem ela, os e-mails entram em modo DRY-RUN e aparecem apenas no log |
| `RESEND_FROM` | `onboarding@resend.dev` | remetente dos e-mails |
| `MOCK_WEBHOOK_SECRET` | `WEBHOOK_SECRET` | segredo compartilhado entre o Mock e o webhook |
| `INTERVALO_PROMOCAO` | `20` (`.env.example`: `8`) | segundos entre promocoes geradas |
| `RABBIT_HOST` / `RABBIT_PORT` | `localhost` / `5672` | endereco do broker |

A chave do Resend e lida apenas da variavel de ambiente e nunca e versionada
(o `.env` esta no `.gitignore`).

### 4. Subir os processos

Um terminal por processo (no Windows, troque `.venv/bin/python` por
`.venv\Scripts\python`):

```bash
.venv/bin/python -m ms_estoque.main        # :8002
.venv/bin/python -m mock_pagamento.main    # :8004
.venv/bin/python -m ms_pagamento.main      # :8003
.venv/bin/python -m ms_entrega.main
.venv/bin/python -m ms_promocoes.main
.venv/bin/python -m ms_principal.main      # :8000 (API Gateway)

cd frontend && npm run dev                 # :5173 (interface)
```

Alternativa: `./run_services.sh start` (ou `.\run_services.ps1 start` no
Windows) sobe os 6 processos do backend em background, com logs em `logs/`;
`stop` encerra todos.

Abra <http://localhost:5173>.

Estoque inicial: `P1=10 P2=5 P3=0 P4=3 P5=7 P6=2`. O `P3` comeca zerado para
demonstrar `estoque.indisponivel`. Para restaurar, apague
`ms_estoque/estoque.db` com o servico parado.

## Estrutura

```
common/          envelope, criptografia, conexao RabbitMQ, base dos microsservicos
ms_principal/    API Gateway: rotas REST, SSE e consumidor de eventos
ms_estoque/      estoque persistido em SQLite + GET /produtos
ms_pagamento/    cobranca no Mock + webhook
ms_entrega/      emissao de nota fiscal e envio
ms_promocoes/    interesses, geracao de promocoes e e-mail (Resend)
mock_pagamento/  provedor de pagamento externo (nao usa AMQP nem chaves)
frontend/        React + Vite + TypeScript
tools/           geracao das chaves RSA
```

As chaves privadas (`*.key.pem`) ficam fora do git; as publicas (`*.pub.pem`)
sao versionadas.

## Limitacoes conhecidas

- A lista de pedidos do gateway fica em memoria: reiniciar o gateway a zera.
  O estoque e persistido.
- Se o webhook de aprovacao chegar ao `ms_pagamento` antes do
  `pedido.excluido` de uma exclusao simultanea, o pedido pode ser enviado
  mesmo cancelado no gateway; tratar isso exigiria compensacao (estorno).
