"""Base dos consumidores de promocoes C1 e C2"""

import logging
from typing import override

from common.service import Microservice

log = logging.getLogger(__name__)


class ConsumidorPromocoes(Microservice):

    publica = False  # sem chave privada, pois so consome

    @override
    def handle(self, event, payload):
        log.info(
            f"{event} | {payload['nome']} (cat {payload['categoria']}): "
            f"{payload['descontoPct']}% OFF  "
            f"R$ {payload['precoOriginal']:.2f} -> R$ {payload['precoPromocional']:.2f}"
        )
