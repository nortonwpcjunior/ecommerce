"""Base dos consumidores de promocoes (C1 e C2).

Estes processos NAO sao microsservicos: nao publicam nada, nao tem chave
privada (publica=False) e nao conversam com nenhum outro processo. Falam
exclusivamente com o RabbitMQ, consumindo a exchange Promocoes (topic) e
validando a assinatura do ms_promocoes.
"""

import logging

from common.service import EX_PROMOCOES, Microservice

log = logging.getLogger(__name__)


class ConsumidorPromocoes(Microservice):
    publica = False          # sem chave privada: so consome
    padroes = []             # padroes de binding na exchange topic

    def __init__(self):
        type(self).bindings = [(EX_PROMOCOES, p) for p in self.padroes]
        super().__init__()

    def handle(self, event, payload):
        log.info(
            "%s | %s (cat %s): %d%% OFF  R$ %.2f -> R$ %.2f",
            event,
            payload["nome"],
            payload["categoria"],
            payload["descontoPct"],
            payload["precoOriginal"],
            payload["precoPromocional"],
        )
