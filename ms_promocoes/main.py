#!/usr/bin/env python3
"""Microsservico Promocoes.

    Publica:  promocao.categoria.A | .B | .C   (exchange Promocoes, topic)

Nao consome nenhum evento: apenas gera promocoes aleatorias em intervalos
regulares. A routing key hierarquica carrega a categoria do produto, o que
permite que C1 e C2 assinem por padrao de binding.
"""

import logging
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.catalogo import PRODUTOS  # noqa: E402
from common.eventos import promocao_de  # noqa: E402
from common.service import EX_PROMOCOES, Publisher, configurar_log  # noqa: E402

NOME = "ms_promocoes"
log = logging.getLogger(NOME)

INTERVALO = int(os.getenv("INTERVALO_PROMOCAO", "8"))  # segundos
DESCONTOS = [5, 10, 15, 20, 25, 30, 40, 50]


def main():
    configurar_log(NOME)
    publisher = Publisher(NOME)
    log.info(f"publicando em {EX_PROMOCOES} a cada {INTERVALO}s (Ctrl+C para sair)")

    try:
        while True:
            produto_id = random.choice(list(PRODUTOS))
            produto = PRODUTOS[produto_id]
            desconto = random.choice(DESCONTOS)
            preco_final = round(produto["preco"] * (1 - desconto / 100.0), 2)

            routing_key = promocao_de(produto["categoria"])
            log.info(f"{routing_key}: {produto['nome']} com {desconto}% OFF "
                     f"(R$ {produto['preco']:.2f} -> R$ {preco_final:.2f})")

            publisher.publish(EX_PROMOCOES, routing_key, {
                "produtoId": produto_id,
                "nome": produto["nome"],
                "categoria": produto["categoria"],
                "descontoPct": desconto,
                "precoOriginal": produto["preco"],
                "precoPromocional": preco_final,
            })
            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        publisher.close()
        log.info("encerrado")


if __name__ == "__main__":
    main()
