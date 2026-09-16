"""Infraestrutura de mensageria: conexao, topologia, publicacao e consumo.

Regra de ouro do pika: uma BlockingConnection NAO e thread-safe. Cada thread
que fala com o broker precisa da sua propria conexao. E por isso que o
ms_principal abre uma conexao para o consumidor (thread de fundo) e outra para
o menu (thread principal).
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pika
import pika.exceptions

from common.crypto import (
    AssinaturaInvalida,
    Signer,
    Verifier,
    load_private,
    load_public_keys,
    sha256_hex,
)
from common.envelope import Envelope

ROOT = Path(__file__).resolve().parent.parent

# As duas exchanges exigidas pelo enunciado. Nenhuma fanout.
EX_ECOMMERCE = "eCommerce"      # tipo direct -> casamento exato da routing key
EX_PROMOCOES = "Promocoes"      # tipo topic  -> casamento por padrao (* e #)

log = logging.getLogger(__name__)


def configurar_log(nome_processo: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{nome_processo}] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)  # pika e muito verboso


def keys_dir(nome_processo: str) -> Path:
    return ROOT / nome_processo / "keys"


def connect(heartbeat: int = 60):
    """Abre conexao e canal.

    heartbeat=0 desliga o heartbeat. Use em conexoes que ficam ociosas por
    muito tempo: o pika so processa heartbeats quando o codigo chama a
    biblioteca, e a thread do menu fica parada em input(). Com heartbeat
    ligado, o broker derruba a conexao por timeout e a proxima publicacao
    falha com StreamLostError.
    """
    params = pika.ConnectionParameters(
        host=os.getenv("RABBIT_HOST", "localhost"),
        port=int(os.getenv("RABBIT_PORT", "5672")),
        credentials=pika.PlainCredentials(
            os.getenv("RABBIT_USER", "guest"), os.getenv("RABBIT_PASS", "guest")
        ),
        heartbeat=heartbeat,
        blocked_connection_timeout=30,
    )
    try:
        conexao = pika.BlockingConnection(params)
    except pika.exceptions.AMQPConnectionError:
        sys.exit(
            f"\n[ERRO] Nao foi possivel conectar ao RabbitMQ em {params.host}:{params.port}.\n"
            "       Suba o broker com:  docker compose up -d\n"
        )
    return conexao, conexao.channel()


def declare_topology(canal) -> None:
    """Declara as duas exchanges. Idempotente: todo processo pode chamar."""
    canal.exchange_declare(EX_ECOMMERCE, exchange_type="direct", durable=True)
    canal.exchange_declare(EX_PROMOCOES, exchange_type="topic", durable=True)


# --------------------------------------------------------------------------
# Publicacao
# --------------------------------------------------------------------------

class Publisher:
    """Publica eventos assinados com a chave privada do processo.

    Com `canal` informado, reutiliza o canal de um consumidor existente
    (obrigatorio ao publicar de dentro de um callback de consumo, para nao
    misturar conexoes na mesma thread). Sem canal, abre conexao propria com
    heartbeat desligado.
    """

    def __init__(self, nome: str, canal=None):
        self.nome = nome
        self.signer = Signer(load_private(keys_dir(nome) / f"{nome}.key.pem"))
        self._canal_emprestado = canal is not None
        self._conexao = None
        self._canal = canal
        if canal is None:
            self._abrir()

    def _abrir(self) -> None:
        self._conexao, self._canal = connect(heartbeat=0)
        declare_topology(self._canal)

    def publish(self, exchange: str, routing_key: str, payload: dict) -> None:
        envelope = Envelope(
            producer=self.nome,
            event=routing_key,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
        )
        assinados = envelope.dados_assinados()
        envelope.signature = self.signer.sign(assinados)

        corpo = envelope.to_bytes()
        propriedades = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # mensagem persistente
            app_id=self.nome,
        )

        try:
            self._canal.basic_publish(exchange, routing_key, corpo, propriedades)
        except (pika.exceptions.AMQPError, pika.exceptions.StreamLostError):
            if self._canal_emprestado:
                raise  # o dono do canal (o consumidor) cuida da reconexao
            log.warning("conexao de publicacao caiu; reconectando")
            self._abrir()
            self._canal.basic_publish(exchange, routing_key, corpo, propriedades)

        log.info(f"--> publicado {routing_key} em {exchange} "
                 f"(hash {sha256_hex(assinados)[:16]})")

    def close(self) -> None:
        if not self._canal_emprestado and self._conexao is not None:
            try:
                self._conexao.close()
            except pika.exceptions.AMQPError:
                pass


# --------------------------------------------------------------------------
# Consumo
# --------------------------------------------------------------------------

class Microservice:
    """Base de todo microsservico: consome, verifica a assinatura e despacha.

    Subclasses definem name, queue e bindings, e implementam handle().
    Eventos com assinatura invalida sao descartados sem chegar ao handle().
    """

    name = ""
    queue = ""
    bindings = []   # lista de (exchange, routing_key)
    publica = True  # False para consumidores que nunca publicam (sem chave privada)

    def __init__(self):
        configurar_log(self.name)
        self.conexao, self.channel = connect()
        self.verifier = Verifier(load_public_keys(keys_dir(self.name)))
        self.publisher = Publisher(self.name, canal=self.channel) if self.publica else None

    # ---- ciclo de vida -------------------------------------------------

    def setup(self) -> None:
        declare_topology(self.channel)
        # Cada consumidor cria a SUA propria fila e faz os bindings dela.
        self.channel.queue_declare(self.queue, durable=True)
        for exchange, routing_key in self.bindings:
            self.channel.queue_bind(self.queue, exchange, routing_key)
            log.info(f"binding: {self.queue} <- '{routing_key}' ({exchange})")
        # Um evento por vez: ordem de processamento previsivel.
        self.channel.basic_qos(prefetch_count=1)

    def start(self) -> None:
        self.setup()
        produtores = ", ".join(self.verifier.produtores_conhecidos())
        log.info(f"chaves publicas carregadas: {produtores}")
        self.channel.basic_consume(self.queue, self._ao_receber, auto_ack=False)
        log.info(f"aguardando eventos em {self.queue} (Ctrl+C para sair)")
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.channel.stop_consuming()
        finally:
            try:
                self.conexao.close()
            except pika.exceptions.AMQPError:
                pass
            log.info("encerrado")

    # ---- consumo -------------------------------------------------------

    def _ao_receber(self, canal, method, propriedades, corpo) -> None:
        tag = method.delivery_tag

        try:
            envelope = Envelope.from_bytes(corpo)
        except (ValueError, UnicodeDecodeError) as exc:
            log.error(f"corpo invalido em {method.routing_key} ({exc}): "
                      "evento DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        # A routing key da entrega tem de casar com o evento assinado, senao
        # um envelope valido poderia ser reencaminhado para outra fila.
        if envelope.event != method.routing_key:
            log.error(f"routing key '{method.routing_key}' diferente do evento "
                      f"assinado '{envelope.event}': DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        # Validacao da assinatura ANTES de qualquer processamento.
        try:
            self.verifier.verificar(envelope)
        except AssinaturaInvalida as exc:
            log.error(f"ASSINATURA INVALIDA em {method.routing_key} ({exc}): "
                      "evento DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        log.info(f"<-- {envelope.event} de {envelope.producer} (assinatura OK)")

        try:
            self.handle(envelope.event, envelope.payload)
        except Exception:
            # Sem requeue: o evento voltaria em loop e travaria a fila.
            log.exception(f"erro ao processar {envelope.event}: evento DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        canal.basic_ack(tag)

    def handle(self, event: str, payload: dict) -> None:
        raise NotImplementedError

    # ---- atalho de publicacao -----------------------------------------

    def publish(self, exchange: str, routing_key: str, payload: dict) -> None:
        if self.publisher is None:
            raise RuntimeError(f"{self.name} foi criado com publica=False")
        self.publisher.publish(exchange, routing_key, payload)
