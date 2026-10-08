"""MS Pagamento: pede a cobranca ao Mock e recebe a decisao por webhook.

No Trab1 este servico sorteava o resultado (TAXA_APROVACAO). Agora quem
decide e o usuario, clicando numa aba do Mock de Pagamento -- entao o fluxo
deixa de ser sincrono: o handle() so ABRE a cobranca, e a resposta chega
depois, por HTTP, na rota do webhook.
"""

import logging
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import override

import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.eventos import Evento  # noqa: E402
from common.http import (  # noqa: E402
    cliente,
    com_consumidor,
    criar_app,
    registrar_health,
    rodar,
)
from common.service import EX_ECOMMERCE, Microservice, PublisherHTTP  # noqa: E402

NOME = "ms_pagamento"
PORTA = int(os.getenv("PAGAMENTO_PORTA", "8003"))

MOCK_URL = os.getenv("MOCK_URL", "http://localhost:8004")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", f"http://localhost:{PORTA}/webhook/pagamento")
SEGREDO = os.getenv("MOCK_WEBHOOK_SECRET", "segredo-de-demonstracao")

log = logging.getLogger(NOME)

# Um worker so: a chamada ao Mock sai daqui enquanto a thread do pika fica
# bombeando a conexao (ver Microservice.aguardar).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mock")


class Pendentes:
    """Pedidos com cobranca aberta, aguardando o clique do usuario.

    Escrito pela thread do pika e lido pela thread do webhook, dai o lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pedidos: dict[str, dict] = {}
        self._resolvidos: set[str] = set()

    def abrir(self, pedido_id: str, valor: float, itens: list) -> None:
        with self._lock:
            self._pedidos[pedido_id] = {"valor": valor, "itens": itens}

    def resolver(self, pedido_id: str) -> dict | None:
        """Fecha o pedido. Devolve None se ele ja tinha sido resolvido.

        E a idempotencia do webhook: dois cliques no Mock, ou um reenvio da
        cobranca, nao podem virar dois eventos de pagamento contraditorios.
        """
        with self._lock:
            if pedido_id in self._resolvidos:
                return None
            self._resolvidos.add(pedido_id)
            return self._pedidos.pop(pedido_id, {"valor": 0.0, "itens": []})

    def conhecido(self, pedido_id: str) -> bool:
        with self._lock:
            return pedido_id in self._pedidos or pedido_id in self._resolvidos


PENDENTES = Pendentes()


class MsPagamento(Microservice):
    name = NOME
    queue = "fila.pagamento"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK),
    ]

    @override
    def handle(self, event, payload):
        if event != Evento.PEDIDO_ESTOQUE_OK:
            return

        pedido_id = payload["pedidoId"]
        valor = payload.get("total", 0.0)
        itens = payload.get("itens", [])

        if PENDENTES.conhecido(pedido_id):
            log.info(f"cobranca de {pedido_id} ja aberta -- ignorando duplicata")
            return

        PENDENTES.abrir(pedido_id, valor, itens)

        try:
            # A chamada HTTP roda noutra thread e aguardar() mantem a conexao
            # do pika viva enquanto isso -- sem esse cuidado, o broker
            # derrubaria a conexao e a mensagem voltaria por redelivery.
            cobranca = self.aguardar(_executor.submit(
                self._criar_cobranca, pedido_id, valor
            ))
        except httpx.HTTPError as exc:
            log.error(f"mock de pagamento indisponivel ({exc})")
            PENDENTES.resolver(pedido_id)
            self.publish(EX_ECOMMERCE, Evento.PAGAMENTO_RECUSADO, {
                "pedidoId": pedido_id,
                "valor": valor,
                "motivo": "mock de pagamento indisponivel",
            })
            return

        log.info(f"cobranca aberta para {pedido_id}: {cobranca['checkoutUrl']}")

        # O gateway repassa esta URL ao navegador pelo SSE -- e o unico caminho
        # possivel, ja que o MS Pagamento nao fala com o frontend.
        self.publish(EX_ECOMMERCE, Evento.PAGAMENTO_PENDENTE, {
            "pedidoId": pedido_id,
            "valor": valor,
            "checkoutUrl": cobranca["checkoutUrl"],
        })

    @staticmethod
    def _criar_cobranca(pedido_id: str, valor: float) -> dict:
        resposta = cliente.post(
            f"{MOCK_URL}/cobrancas",
            json={
                "pedidoId": pedido_id,
                "valor": valor,
                "webhookUrl": WEBHOOK_URL,
            },
        )
        resposta.raise_for_status()
        return resposta.json()


class Decisao(BaseModel):
    pedidoId: str
    status: str
    cobrancaId: str = ""
    valor: float = 0.0


def _abrir_publisher(app, servico):
    app.state.publisher = PublisherHTTP(NOME)


def _fechar_publisher(app, servico):
    app.state.publisher.close()


app = criar_app(
    "MS Pagamento",
    lifespan=com_consumidor(MsPagamento, _abrir_publisher, _fechar_publisher),
)
registrar_health(app)


@app.post("/webhook/pagamento")
def webhook(decisao: Decisao, x_webhook_secret: str = Header(default="")):
    """Recebe a decisao do Mock e publica o evento correspondente.

    Rota sincrona (def) de proposito: ela publica no broker, operacao
    bloqueante, e vai para o threadpool em vez de travar o event loop.
    """
    # Sem este confere, qualquer um que alcance a porta aprova qualquer pedido
    # -- e o evento sairia assinado por este servico, fazendo a cadeia de
    # assinatura atestar um dado forjado.
    if x_webhook_secret != SEGREDO:
        log.warning(f"webhook com segredo invalido para {decisao.pedidoId}")
        raise HTTPException(401, "segredo invalido")

    status = decisao.status.upper()
    if status not in ("APROVADO", "RECUSADO"):
        raise HTTPException(400, "status deve ser APROVADO ou RECUSADO")

    pedido = PENDENTES.resolver(decisao.pedidoId)
    if pedido is None:
        log.info(f"{decisao.pedidoId} ja resolvido -- webhook ignorado")
        return {"ok": True, "duplicata": True}

    valor = pedido["valor"] or decisao.valor

    if status == "APROVADO":
        autorizacao = f"AUT-{random.randint(0, 999999):06d}"
        log.info(f"APROVADO ({autorizacao}) para {decisao.pedidoId}")
        app.state.publisher.publish(EX_ECOMMERCE, Evento.PAGAMENTO_APROVADO, {
            "pedidoId": decisao.pedidoId,
            "valor": valor,
            "autorizacao": autorizacao,
            "itens": pedido["itens"],
        })
    else:
        log.info(f"RECUSADO para {decisao.pedidoId}")
        app.state.publisher.publish(EX_ECOMMERCE, Evento.PAGAMENTO_RECUSADO, {
            "pedidoId": decisao.pedidoId,
            "valor": valor,
            "motivo": "recusado pelo usuario no checkout",
        })

    return {"ok": True, "duplicata": False}


if __name__ == "__main__":
    rodar(app, PORTA, NOME)
