"""Envelope de evento enviado ao RabbitMQ.
    {
      "producer":  "ms_estoque",           # quem assinou -> define a chave publica
      "event":     "pedido.estoque_ok",    # routing key do evento
      "timestamp": "2026-09-11T13:04:55+00:00",
      "payload":   { ... },                # conteudo do evento
      "signature": "<base64>"              # assinatura dos campos acima
    }
"""

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Self


def canon(obj) -> bytes:
    """Serializacao canonica: chaves ordenadas, sem espacos."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


@dataclass
class Envelope:
    producer: str
    event: str
    timestamp: str
    payload: dict = field(default_factory=dict)
    signature: str = ""

    def dados_assinados(self) -> bytes:
        """Os bytes exatos que sao assinados e verificados sem o campo signature."""
        return canon({
            "producer": self.producer,
            "event": self.event,
            "timestamp": self.timestamp,
            "payload": self.payload,
        })

    def to_bytes(self) -> bytes:
        return canon(asdict(self))

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        dados = json.loads(raw)
        if not isinstance(dados, dict):
            raise ValueError("envelope nao e um objeto JSON")
        conhecidos = {f.name for f in fields(cls)}
        faltando = conhecidos - dados.keys()
        if faltando:
            raise ValueError(f"envelope sem os campos: {', '.join(sorted(faltando))}")
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})
