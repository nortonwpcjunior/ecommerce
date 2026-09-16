"""Base dos consumidores de promocoes (C1 e C2).

Estes processos NAO sao microsservicos: nao publicam nada, nao tem chave
privada (publica=False) e nao conversam com nenhum outro processo. Falam
exclusivamente com o RabbitMQ, consumindo a exchange Promocoes (topic) e
validando a assinatura do ms_promocoes.
"""

import logging
from typing import override

from common.service import Microservice

log = logging.getLogger(__name__)


class ConsumidorPromocoes(Microservice):
    """So o que C1 e C2 tem em comum: nao publicam e imprimem a promocao.

    Cada consumidor declara os proprios `bindings`, como qualquer outro
    processo do projeto.
    """

    publica = False          # sem chave privada: so consome

    @override
    def handle(self, event, payload):
        log.info(
            f"{event} | {payload['nome']} (cat {payload['categoria']}): "
            f"{payload['descontoPct']}% OFF  "
            f"R$ {payload['precoOriginal']:.2f} -> R$ {payload['precoPromocional']:.2f}"
        )
