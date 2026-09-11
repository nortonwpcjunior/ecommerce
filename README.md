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

## Estrutura

```
ecommerce-mom/
├── common/
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
├── run_services.sh
└── docker-compose.yml
```

## Fluxo dos eventos

```
        usuario
           |  (menu no terminal)
      ms_principal ---- pedido.criado -----------> ms_estoque
           |                                            |
           |<--------- pedido.estoque_ok ---------------|
           |<--------- estoque.indisponivel ------------|
           |                                            ^
           |--------- pedido.excluido ------------------'  (devolve ao estoque)
           |
           |            ms_estoque -- pedido.estoque_ok --> ms_pagamento
           |<--------- pagamento.aprovado --------------------|
           |<--------- pagamento.recusado --------------------|
           |
           |         ms_pagamento -- pagamento.aprovado --> ms_entrega
           |<--------- pedido.enviado ------------------------|

    ms_promocoes -- promocao.categoria.X --> [C1: A e B]  [C2: *]
```

---

## Como rodar

### 1. Broker

```bash
docker compose up -d          # RabbitMQ em localhost:5672
                              # painel: http://localhost:15672 (guest/guest)
```

Se **ja houver** um RabbitMQ ocupando a 5672 (foi o caso nesta maquina, container
`sd-rabbitmq`), pule este passo: o projeto usa o broker que estiver no ar.
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

## Ferramentas de verificacao

```bash
.venv/bin/python -m tools.test_crypto              # assina/verifica sem broker
.venv/bin/python -m tools.smoke_test P1 2          # fluxo ponta a ponta, sem menu
.venv/bin/python -m tools.test_assinatura_invalida # prova que evento forjado e descartado
```

`test_assinatura_invalida` publica quatro eventos -- legitimo, payload
adulterado, assinado com a chave de outro servico, e um evento substituido
(payload legitimo de `pedido.estoque_ok` republicado como
`pagamento.aprovado`) -- e apenas o primeiro e processado. Bom roteiro para a
pergunta "e se alguem forjar um evento?".

`test_crypto` roda 9 verificacoes de assinatura sem precisar do broker.

Para forcar recusa de pagamento na demonstracao:
`TAXA_APROVACAO=0 .venv/bin/python -m ms_pagamento.main` (padrao: `0.7`).

---

## Decisoes de projeto (o que defender)

**1. A assinatura cobre `producer` + `event` + `timestamp` + `payload`**, nao
apenas o payload. Assinando so o payload, um atacante pega um envelope valido,
troca a routing key e o campo `event`, e reaproveita a assinatura: um payload
assinado para `pedido.estoque_ok` passa como `pagamento.aprovado` e o
`ms_entrega` emite nota fiscal de um pedido nunca pago. Isso foi testado e
confirmado antes da correcao -- ver `tools/test_assinatura_invalida.py`, caso 4.

**2. Serializacao canonica (`canon`)**: `sort_keys=True` e sem espacos. Os
mesmos dados produzem sempre os mesmos bytes, no produtor e no consumidor. E a
causa numero 1 de "assinatura invalida" inexplicavel.

**3. O hash e calculado explicitamente** (`sha256_digest`) e a assinatura usa
`utils.Prehashed`. Os tres passos do enunciado ficam separados no codigo:
gerar o hash, assinar com a privada, por no campo `signature`. O hash aparece
tambem nos logs de publicacao, para conferencia na demonstracao.

**4. A assinatura e verificada ANTES de processar**, em
`Microservice._ao_receber`. Assinatura invalida -> `basic_nack(requeue=False)`:
o evento e descartado e nunca chega ao `handle()`.

**5. A routing key da entrega tem de casar com o `event` assinado.** Defesa
extra: um envelope valido reencaminhado para outra fila e recusado.

**6. `heartbeat=0` na conexao de publicacao.** O pika so processa heartbeats
quando o codigo chama a biblioteca, e a thread do menu fica parada em
`input()`. Com heartbeat ligado, o broker derruba a conexao por timeout e o
proximo pedido falha com `StreamLostError` -- acontece em ~2 minutos de menu
aberto. A conexao do consumidor mantem `heartbeat=60`, porque ela nunca fica
ociosa dentro da biblioteca.

**7. O `Publisher` reconecta** se a conexao propria cair. Quando o canal e
emprestado do consumidor, a excecao sobe: quem reconecta e o dono do canal.

**8. O `ms_principal` usa DUAS conexoes.** O `BlockingConnection` do pika nao e
thread-safe. A thread do consumidor usa a conexao de `Microservice`; a thread
do menu usa um `Publisher` com conexao propria. E publicar sempre FORA do
lock, para nao prender a thread do menu durante a ida ao broker.

**9. `prefetch_count=1`**: um evento por vez por consumidor, ordem de
processamento previsivel.

**10. Filas duraveis e mensagens persistentes** (`delivery_mode=2`): derrubar
um microsservico nao perde eventos, ele reprocessa ao voltar.

**11. O ID do pedido leva um sufixo de sessao** (`PED-A3F1-001`). Sem isso,
reiniciar o `ms_principal` reinicia o contador em 1 e os IDs colidem com o
estado que `ms_estoque` e `ms_pagamento` ainda mantem em memoria.

**12. Evento para pedido desconhecido e registrado e ignorado.** O
`ms_principal` e a unica origem de pedidos; um `pedidoId` que ele nao criou
nunca vira um pedido na lista do usuario.

**13. Idempotencia no `ms_estoque` e no `ms_entrega`**: `pedido.criado`
repetido nao reserva duas vezes, `pagamento.aprovado` repetido nao emite duas
notas. Necessario porque a entrega do RabbitMQ e at-least-once.

**14. As quantidades em estoque vivem APENAS no `ms_estoque`.**
`common/catalogo.py` tem so os dados cadastrais do produto -- e uma tabela de
referencia carregada localmente, como um arquivo de configuracao, nao uma
chamada entre processos. Por isso o menu nao mostra saldo: nao ha como
consultar sem chamada direta, que o enunciado proibe.

**15. Consumidores de promocoes usam `publica=False`** e nao tem chave
privada. Nao podem publicar nada nem falar com microsservico algum, so com o
broker.

## Observacoes

- As chaves **privadas** (`*.key.pem`, permissao 0600) estao no `.gitignore`.
  As **publicas** (`*.pub.pem`) sao versionadas, como pede a especificacao.
- Ao rodar o menu, os eventos chegam em outra thread e imprimem no console.
  Se a tela embolar durante uma digitacao, ENTER redesenha o menu.
- Testado com Python 3.13, pika 1.3.2, cryptography 43.0.3, RabbitMQ 3.13.
- A camada `common/` incorpora o tratamento de envelope, heartbeat e reconexao
  de uma versao anterior deste trabalho (`~/ecommerce`), que resolvia esses
  tres pontos melhor.
