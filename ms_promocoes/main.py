"""MS Promocoes: cadastra interesses e notifica por e-mail.

Diferente do Trab1, onde era um produtor puro. Agora e um Microservice com
UMA fila e DOIS bindings, em exchanges diferentes:

    (eCommerce, interesse.promocao)   -> cadastra/remove e-mail e categorias
    (Promocoes, promocao.categoria.*) -> dispara o e-mail aos interessados

Mais uma thread geradora que publica promocao.categoria.{A,B,C} no topic
exchange. Ou seja: ele consome a propria promocao que acabou de publicar.
Parece volta desnecessaria, mas e o que mantem geracao e notificacao
desacopladas -- e o que preserva o topic exchange e o curinga, que os
consumidores C1/C2 do Trab1 demonstravam e que sairam da arquitetura do
Trab2.
"""

import logging
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.catalogo import PRODUTOS  # noqa: E402
from common.eventos import Evento  # noqa: E402
from common.http import cliente  # noqa: E402
from common.service import (  # noqa: E402
    EX_ECOMMERCE,
    EX_PROMOCOES,
    Microservice,
    Publisher,
    encerrar_na_falha,
)

from ms_promocoes import interesses, notificacao  # noqa: E402

NOME = "ms_promocoes"
log = logging.getLogger(NOME)

INTERVALO = int(os.getenv("INTERVALO_PROMOCAO", "8"))  # segundos
DESCONTOS = [5, 10, 15, 20, 25, 30, 40, 50]

_parar = threading.Event()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="email")


class MsPromocoes(Microservice):
    name = NOME
    queue = "fila.promocoes"
    bindings = [
        (EX_ECOMMERCE, Evento.INTERESSE_PROMOCAO),
        # O curinga casa exatamente uma palavra, entao cobre qualquer
        # categoria -- inclusive as que venham a existir.
        (EX_PROMOCOES, "promocao.categoria.*"),
    ]
    # A fila e duravel: sem TTL, o gerador parado por horas acumularia
    # promocoes velhas e viraria uma enxurrada de e-mails no restart.
    queue_args = {"x-message-ttl": 60_000, "x-max-length": 100}

    def setup(self):
        super().setup()
        interesses.carregar()
        log.info(f"{interesses.total()} interesse(s) carregado(s); "
                 f"envio de e-mail em modo {notificacao.modo()}")

    @override
    def handle(self, event, payload):
        if event == Evento.INTERESSE_PROMOCAO:
            self._interesse(payload)
        else:  # promocao.categoria.X
            self._promocao(event, payload)

    @staticmethod
    def _interesse(payload):
        email = payload.get("email", "").strip()
        if not email:
            log.warning("interesse sem e-mail -- ignorado")
            return

        if payload.get("acao") == "cancelar":
            if interesses.cancelar(email):
                log.info(f"interesse de {email} cancelado")
            else:
                log.info(f"{email} nao tinha interesse cadastrado")
            return

        categorias = interesses.registrar(email, payload.get("categorias", []))
        log.info(f"{email} quer promocoes das categorias {', '.join(categorias) or '-'}")

    def _promocao(self, event, payload):
        categoria = payload["categoria"]
        destinos = interesses.interessados(categoria)

        log.info(f"{event} | {payload['nome']} (cat {categoria}): "
                 f"{payload['descontoPct']}% OFF  "
                 f"R$ {payload['precoOriginal']:.2f} -> "
                 f"R$ {payload['precoPromocional']:.2f}  "
                 f"-> {len(destinos)} interessado(s)")

        if not destinos:
            return

        assunto = (f"{payload['descontoPct']}% OFF em {payload['nome']}")
        html = notificacao.montar_html(payload)
        # Fora da thread do pika, com a conexao sendo bombeada: uma chamada
        # lenta ao Resend nao pode derrubar a conexao com o broker.
        self.aguardar(_executor.submit(
            notificacao.enviar, cliente, destinos, assunto, html
        ))


def gerar_promocoes():
    """Thread produtora: Publisher PROPRIO, nunca o canal do consumidor."""
    publisher = Publisher(NOME)
    log.info(f"publicando em {EX_PROMOCOES} a cada {INTERVALO}s")
    try:
        while not _parar.is_set():
            produto_id = random.choice(list(PRODUTOS))
            produto = PRODUTOS[produto_id]
            desconto = random.choice(DESCONTOS)
            preco_final = round(produto["preco"] * (1 - desconto / 100.0), 2)

            publisher.publish(
                EX_PROMOCOES,
                f"promocao.categoria.{produto['categoria']}",
                {
                    "produtoId": produto_id,
                    "nome": produto["nome"],
                    "categoria": produto["categoria"],
                    "descontoPct": desconto,
                    "precoOriginal": produto["preco"],
                    "precoPromocional": preco_final,
                },
            )
            # wait(), nao sleep(): o shutdown nao espera o intervalo inteiro.
            _parar.wait(INTERVALO)
    finally:
        publisher.close()


def main():
    servico = MsPromocoes()

    gerador = threading.Thread(target=gerar_promocoes, name="gerador", daemon=True)
    gerador.start()

    try:
        servico.start()
    finally:
        _parar.set()
        gerador.join(timeout=INTERVALO + 2)
        _executor.shutdown(wait=False)
        cliente.close()


if __name__ == "__main__":
    encerrar_na_falha(main)
