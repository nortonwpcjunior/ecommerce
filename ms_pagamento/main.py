import httpx
import logging
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import Header, HTTPException
from pathlib import Path
from pydantic import BaseModel
from typing import override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.eventos import Evento  # noqa: E402
from common.http import (  # noqa: E402
    cliente,
    com_consumidor,
    criar_app,
    rodar,
)
from common.service import EX_ECOMMERCE, Microservice, PublisherHTTP  # noqa: E402

NOME = "ms_pagamento"
PORTA = int(os.getenv("PAGAMENTO_PORTA", "8003"))

MOCK_URL = os.getenv("MOCK_URL", "http://localhost:8004")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", f"http://localhost:{PORTA}/webhook/pagamento")
SECRET = os.getenv("MOCK_WEBHOOK_SECRET", "WEBHOOK_SECRET")

log = logging.getLogger(NOME)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mock")


class Pendentes:

    def __init__(self):
        self._lock = threading.Lock()
        self._pedidos: dict[str, dict] = {}
        self._resolvidos: set[str] = set()
        self._cancelados: set[str] = set()

    def abrir(self, pedido_id: str, valor: float, itens: list) -> None:
        with self._lock:
            self._pedidos[pedido_id] = {"valor": valor, "itens": itens}

    def resolver(self, pedido_id: str) -> dict | None:
        with self._lock:
            if pedido_id in self._resolvidos:
                return None
            self._resolvidos.add(pedido_id)
            return self._pedidos.pop(pedido_id, {"valor": 0.0, "itens": []})

    def cancelar(self, pedido_id: str) -> bool:
        with self._lock:
            if pedido_id in self._resolvidos:
                return False
            self._resolvidos.add(pedido_id)
            self._cancelados.add(pedido_id)
            self._pedidos.pop(pedido_id, None)
            return True

    def cancelado(self, pedido_id: str) -> bool:
        with self._lock:
            return pedido_id in self._cancelados

    def conhecido(self, pedido_id: str) -> bool:
        with self._lock:
            return pedido_id in self._pedidos or pedido_id in self._resolvidos


PENDENTES = Pendentes()


class MsPagamento(Microservice):
    name = NOME
    queue = "fila.pagamento"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK),
        (EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO),
    ]

    @override
    def handle(self, event, payload):
        match event:
            case Evento.PEDIDO_ESTOQUE_OK:
                self._abrir_cobranca(payload)
            case Evento.PEDIDO_EXCLUIDO:
                self._cancelar_cobranca(payload)

    def _cancelar_cobranca(self, payload):
        pedido_id = payload["pedidoId"]
        if PENDENTES.cancelar(pedido_id):
            log.info(f"{pedido_id} excluido -- cobranca cancelada, "
                     "o clique no Mock sera ignorado")

    def _abrir_cobranca(self, payload):
        pedido_id = payload["pedidoId"]
        valor = payload.get("total", 0.0)
        itens = payload.get("itens", [])

        if PENDENTES.conhecido(pedido_id):
            log.info(f"cobranca de {pedido_id} ja aberta -- ignorando duplicata")
            return

        PENDENTES.abrir(pedido_id, valor, itens)

        try:
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


def _abrir_publisher(app):
    app.state.publisher = PublisherHTTP(NOME)


def _fechar_publisher(app):
    app.state.publisher.close()


app = criar_app(
    "MS Pagamento",
    lifespan=com_consumidor(MsPagamento, _abrir_publisher, _fechar_publisher),
)


@app.post("/webhook/pagamento")
def webhook(decisao: Decisao, x_webhook_secret: str = Header(default="")):
    if x_webhook_secret != SECRET:
        log.warning(f"webhook secret invalido para {decisao.pedidoId}")
        raise HTTPException(401, "webhook secret invalido")

    status = decisao.status.upper()
    if status not in ("APROVADO", "RECUSADO"):
        raise HTTPException(400, "status deve ser APROVADO ou RECUSADO")

    pedido = PENDENTES.resolver(decisao.pedidoId)
    if pedido is None and PENDENTES.cancelado(decisao.pedidoId):
        log.info(f"{decisao.pedidoId} foi excluido -- {status} ignorado")
        return {"ok": True, "cancelado": True}
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
