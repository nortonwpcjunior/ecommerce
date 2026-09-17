import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.promocao import ConsumidorPromocoes  # noqa: E402
from common.service import EX_PROMOCOES  # noqa: E402


class ConsumidorC1(ConsumidorPromocoes):
    name = "consumidor_c1"
    queue = "fila.C1"
    bindings = [
        (EX_PROMOCOES, "promocao.categoria.A"),
        (EX_PROMOCOES, "promocao.categoria.B"),
    ]


if __name__ == "__main__":
    ConsumidorC1().start()
