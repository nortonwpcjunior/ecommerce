"""Base dos consumidores de promocoes (C1 e C2).

Estes processos NAO sao microsservicos: nao publicam nada, nao tem chave
privada (publica=False) e nao conversam com nenhum outro processo. Falam
exclusivamente com o RabbitMQ, consumindo a exchange Promocoes (topic) e
validando a assinatura do ms_promocoes.
"""

import logging

from common.service import Microservice

log = logging.getLogger(__name__)


class ConsumidorPromocoes(Microservice):
    """So o que C1 e C2 tem em comum: nao publicam e imprimem a promocao.

    Cada consumidor declara os proprios `bindings`, como qualquer outro
    processo do projeto.
    """

    publica = False          # sem chave privada: so consome

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
