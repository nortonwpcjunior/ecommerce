"""Envelope de evento trafegado no RabbitMQ.

    {
      "producer":  "ms_estoque",           # quem assinou -> define a chave publica
      "event":     "pedido.estoque_ok",    # routing key do evento
      "timestamp": "2026-09-11T13:04:55+00:00",
      "payload":   { ... },                # conteudo do evento
      "signature": "<base64>"              # assinatura dos QUATRO campos acima
    }

A assinatura cobre producer + event + timestamp + payload, nao apenas o
payload. Sem isso, um atacante pega um envelope valido, troca a routing key e
o campo `event`, e reaproveita a assinatura: um payload assinado para
pedido.estoque_ok seria aceito como pagamento.aprovado, e o ms_entrega
emitiria nota fiscal de um pedido nunca pago.
"""

import json
from dataclasses import asdict, dataclass, field, fields


def canon(obj) -> bytes:
    """Serializacao canonica: chaves ordenadas, sem espacos.

    Os mesmos dados produzem sempre os mesmos bytes, no produtor e no
    consumidor.
    """
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
        """Os bytes exatos que sao assinados e verificados (sem o signature)."""
        return canon({
            "producer": self.producer,
            "event": self.event,
            "timestamp": self.timestamp,
            "payload": self.payload,
        })

    def to_bytes(self) -> bytes:
        return canon(asdict(self))

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Envelope":
        dados = json.loads(raw)
        if not isinstance(dados, dict):
            raise ValueError("envelope nao e um objeto JSON")
        conhecidos = {f.name for f in fields(cls)}
        faltando = conhecidos - dados.keys()
        if faltando:
            raise ValueError(f"envelope sem os campos: {', '.join(sorted(faltando))}")
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})
