#!/usr/bin/env python3
"""Consumidor C2 -- interessado em TODAS as categorias.

Um unico binding com wildcard '*', que casa exatamente uma palavra:
promocao.categoria.A, .B, .C e qualquer categoria futura.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.eventos import PROMOCAO_TODAS  # noqa: E402
from common.promocao import ConsumidorPromocoes  # noqa: E402
from common.service import EX_PROMOCOES  # noqa: E402


class ConsumidorC2(ConsumidorPromocoes):
    name = "consumidor_c2"
    queue = "fila.C2"
    bindings = [
        (EX_PROMOCOES, PROMOCAO_TODAS),
    ]


if __name__ == "__main__":
    ConsumidorC2().start()
