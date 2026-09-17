import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.promocao import ConsumidorPromocoes  # noqa: E402
from common.service import EX_PROMOCOES  # noqa: E402


class ConsumidorC2(ConsumidorPromocoes):
    name = "consumidor_c2"
    queue = "fila.C2"
    bindings = [
        (EX_PROMOCOES, "promocao.categoria.*"),
    ]


if __name__ == "__main__":
    ConsumidorC2().start()
