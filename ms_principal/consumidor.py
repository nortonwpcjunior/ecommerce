"""A thread consumidora do API Gateway: evento do broker -> estado -> SSE.

E o "tradutor de eventos" da Figura 1. Cada evento que chega do RabbitMQ
atualiza o pedido e e reemitido ao navegador do dono daquele pedido.
"""

import logging
from typing import override

from common.eventos import Evento
from common.service import EX_ECOMMERCE, Microservice

from ms_principal.sse import BARRAMENTO
from ms_principal.store import STORE, Status

NOME = "ms_principal"

log = logging.getLogger(NOME)


class MsPrincipal(Microservice):
    name = NOME
    queue = "fila.principal"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK),
        (EX_ECOMMERCE, Evento.ESTOQUE_INDISPONIVEL),
        (EX_ECOMMERCE, Evento.PAGAMENTO_PENDENTE),
        (EX_ECOMMERCE, Evento.PAGAMENTO_APROVADO),
        (EX_ECOMMERCE, Evento.PAGAMENTO_RECUSADO),
        (EX_ECOMMERCE, Evento.PEDIDO_ENVIADO),
    ]

    @override
    def handle(self, event, payload):
        pedido_id = payload["pedidoId"]

        # O gateway e a unica origem de pedidos: um pedidoId que ele nao criou
        # nunca vira um pedido na lista de alguem.
        if STORE.status_de(pedido_id) is None:
            log.warning(f"evento {event} para pedido desconhecido {pedido_id} "
                        "-- ignorado")
            return

        cancelar_com = None
        retrato = None

        match event:
            case Evento.PEDIDO_ESTOQUE_OK:
                retrato = STORE.atualizar(pedido_id, Status.ESTOQUE_RESERVADO)

            case Evento.ESTOQUE_INDISPONIVEL:
                motivo = payload.get("motivo", "sem estoque")
                retrato = STORE.atualizar(
                    pedido_id, Status.CANCELADO_SEM_ESTOQUE, motivo
                )
                cancelar_com = motivo

            case Evento.PAGAMENTO_PENDENTE:
                checkout = payload.get("checkoutUrl", "")
                retrato = STORE.atualizar(
                    pedido_id,
                    Status.AGUARDANDO_PAGAMENTO,
                    "abra a aba do checkout para pagar",
                    checkoutUrl=checkout,
                )

            case Evento.PAGAMENTO_APROVADO:
                retrato = STORE.atualizar(
                    pedido_id, Status.PAGAMENTO_APROVADO,
                    f"autorizacao {payload.get('autorizacao', '?')}"
                )

            case Evento.PAGAMENTO_RECUSADO:
                motivo = payload.get("motivo", "pagamento recusado")
                retrato = STORE.atualizar(
                    pedido_id, Status.CANCELADO_PAGAMENTO, motivo
                )
                cancelar_com = motivo

            case Evento.PEDIDO_ENVIADO:
                retrato = STORE.atualizar(
                    pedido_id, Status.ENVIADO,
                    f"nota {payload.get('notaFiscal', '?')}, "
                    f"rastreio {payload.get('rastreio', '?')}"
                )

        log.info(f"pedido {pedido_id} -> {STORE.rotulo_de(pedido_id)}")

        if retrato is not None:
            BARRAMENTO.publicar(retrato["cliente"], event, retrato)

        if cancelar_com is not None:
            self.publish(EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO, {
                "pedidoId": pedido_id,
                "motivo": cancelar_com,
                "origem": event,
            })
