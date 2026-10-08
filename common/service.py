"""Infraestrutura de mensageria: conexao, topologia, publicacao e consumo."""

import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pika
import pika.exceptions
from pika.adapters.blocking_connection import BlockingChannel

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

# As duas exchanges, sem fanout.
EX_ECOMMERCE = "eCommerce"  # tipo direct
EX_PROMOCOES = "Promocoes"  # tipo topic

log = logging.getLogger(__name__)


class BrokerIndisponivel(RuntimeError):
    """O RabbitMQ nao respondeu.

    Nao chamamos sys.exit aqui de proposito. Agora que todo servico tem uma
    thread do consumidor alem da thread HTTP, um sys.exit fora da thread
    principal seria ENGOLIDO: o threading trata SystemExit como fim normal da
    thread, entao o consumidor morreria sem traceback e o servidor HTTP
    continuaria respondendo 200 sem processar evento nenhum. Quem chama decide
    o que fazer -- os entrypoints usam encerrar_na_falha().
    """


class BrokerOcupado(RuntimeError):
    """Nao deu para publicar dentro do prazo. Vira HTTP 503."""


def configurar_log(nome_processo: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{nome_processo}] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)


def keys_dir(nome_processo: str) -> Path:
    return ROOT / nome_processo / "keys"


def encerrar_na_falha(funcao):
    """Executa o entrypoint traduzindo falha de broker em mensagem limpa.

    So pode ser usado na thread principal, que e onde sys.exit funciona.
    """
    try:
        funcao()
    except BrokerIndisponivel as exc:
        sys.exit(f"\n[ERRO] {exc}\n")
    except KeyboardInterrupt:
        print()


def connect(heartbeat: int = 60) -> tuple[pika.BlockingConnection, BlockingChannel]:
    """Abre conexao e canal. Levanta BrokerIndisponivel se o broker estiver fora."""
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
    except pika.exceptions.AMQPConnectionError as exc:
        raise BrokerIndisponivel(
            f"Nao foi possivel conectar ao RabbitMQ em {params.host}:{params.port}.\n"
            "       Suba o broker com:  docker compose up -d"
        ) from exc
    return conexao, conexao.channel()


def declare_topology(canal) -> None:
    """Declara as duas exchanges. Idempotente: todo processo pode chamar."""
    canal.exchange_declare(EX_ECOMMERCE, exchange_type="direct", durable=True)
    canal.exchange_declare(EX_PROMOCOES, exchange_type="topic", durable=True)


class Publisher:
    """Publica os eventos assinados"""

    def __init__(
        self,
        nome: str,
        canal: BlockingChannel | None = None,
        confirms: bool = False,
    ):
        self.nome = nome
        self.signer = Signer(load_private(keys_dir(nome) / f"{nome}.key.pem"))
        self._confirms = confirms
        self._canal_emprestado = canal is not None
        self._conexao: pika.BlockingConnection | None = None
        self._canal: BlockingChannel
        if canal is None:
            self._abrir()
        else:
            self._canal = canal

    def _abrir(self) -> None:
        self._conexao, self._canal = connect(heartbeat=0)
        declare_topology(self._canal)
        if self._confirms:
            self._canal.confirm_delivery()

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
            self._publicar(exchange, routing_key, corpo, propriedades)
        except pika.exceptions.AMQPError:
            if self._canal_emprestado:
                raise  # o consumidor cuida da reconexao
            log.warning("conexao de publicacao caiu; reconectando")
            self._abrir()
            self._publicar(exchange, routing_key, corpo, propriedades)

        log.info(f"--> publicado {routing_key} em {exchange} "
                 f"(hash {sha256_hex(assinados)[:16]})")

    def _publicar(self, exchange, routing_key, corpo, propriedades) -> None:
        # mandatory=True so tem efeito com confirms ligados: sem isso a exchange
        # direct descarta em silencio o evento que nenhuma fila escuta, e quem
        # publicou acha que deu certo.
        self._canal.basic_publish(
            exchange, routing_key, corpo, propriedades, mandatory=self._confirms
        )

    def close(self) -> None:
        if not self._canal_emprestado and self._conexao is not None:
            try:
                self._conexao.close()
            except pika.exceptions.AMQPError:
                pass


class PublisherHTTP:
    """Publisher para as threads do servidor HTTP.

    O uvicorn atende cada rota numa thread do pool e o BlockingChannel do pika
    nao e thread-safe, entao toda publicacao passa por um lock -- que cobre
    tambem a reconexao interna do Publisher, que nao e reentrante. O
    acquire tem prazo: com o broker fora, a thread que segura o lock fica
    ~30s no connect, e sem prazo a API inteira congelaria atras dela.
    """

    def __init__(self, nome: str, espera: float = 2.0):
        self._publisher = Publisher(nome, confirms=True)
        self._lock = threading.Lock()
        self._espera = espera

    def publish(self, exchange: str, routing_key: str, payload: dict) -> None:
        if not self._lock.acquire(timeout=self._espera):
            raise BrokerOcupado(f"publicacao de {routing_key} nao obteve a vez")
        try:
            self._publisher.publish(exchange, routing_key, payload)
        except pika.exceptions.UnroutableError as exc:
            raise BrokerOcupado(
                f"nenhuma fila escuta '{routing_key}': o microsservico "
                "responsavel nunca subiu"
            ) from exc
        finally:
            self._lock.release()

    def close(self) -> None:
        self._publisher.close()


class Microservice:
    """Base de todo microsservico: consome, verifica a assinatura e despacha."""

    name = ""
    queue = ""
    bindings: list[tuple[str, str]] = []  # [exchange, routing_key]
    queue_args: dict | None = None
    publica = True

    def __init__(self):
        configurar_log(self.name)
        self.conexao, self.channel = connect()
        self.verifier = Verifier(load_public_keys(keys_dir(self.name)))
        self.publisher = Publisher(self.name, canal=self.channel) if self.publica else None

    def setup(self) -> None:
        declare_topology(self.channel)
        # Cada consumidor cria a sua propria fila e faz os bindings dela.
        self.channel.queue_declare(self.queue, durable=True, arguments=self.queue_args)
        for exchange, routing_key in self.bindings:
            self.channel.queue_bind(self.queue, exchange, routing_key)
            log.info(f"binding: {self.queue} <- '{routing_key}' ({exchange})")
        self.channel.basic_qos(prefetch_count=1)

    def start(self) -> None:
        self.setup()
        produtores = ", ".join(self.verifier.produtores_conhecidos())
        log.info(f"chaves publicas carregadas: {produtores}")
        self.channel.basic_consume(self.queue, self._ao_receber, auto_ack=False)
        log.info(f"aguardando eventos em {self.queue} (Ctrl+C para sair)")
        try:
            self.channel.start_consuming()
        finally:
            try:
                self.conexao.close()
            except pika.exceptions.AMQPError:
                pass
            log.info("encerrado")

    def parar(self) -> None:
        """Pede o fim do consumo A PARTIR DE OUTRA THREAD.

        add_callback_threadsafe e a UNICA api do BlockingConnection que pode
        ser chamada de fora da thread dona da conexao. Chamar stop_consuming
        direto daqui corromperia o estado do pika.
        """
        try:
            self.conexao.add_callback_threadsafe(self.channel.stop_consuming)
        except (pika.exceptions.AMQPError, AssertionError):
            pass

    def aguardar(self, futuro, intervalo: float = 1.0):
        """Espera um Future sem deixar a conexao morrer de inanicao.

        O BlockingConnection nao tem thread de I/O: os heartbeats so trafegam
        quando o codigo esta dentro de uma chamada do pika. Uma chamada HTTP
        feita direto no handle() seguraria a thread por segundos, o broker
        derrubaria a conexao por timeout e o basic_ack seguinte estouraria --
        com a mensagem nunca ackada, ela voltaria por redelivery. Bombeando
        process_data_events a conexao segue viva pelo tempo que precisar.

        So e seguro porque prefetch_count=1: sem outra mensagem em voo, o
        dispatcher do pika nao reentra no handle().
        """
        while not futuro.done():
            self.conexao.process_data_events(time_limit=intervalo)
        return futuro.result()

    # Funcao para consumo de mensagens
    def _ao_receber(self, canal, method, propriedades, corpo) -> None:
        tag = method.delivery_tag

        try:
            envelope = Envelope.from_bytes(corpo)
        except (ValueError, UnicodeDecodeError) as exc:
            log.error(f"corpo invalido em {method.routing_key} ({exc}): "
                      "evento DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        # A routing key da entrega tem que casar com o evento assinado
        if envelope.event != method.routing_key:
            log.error(f"routing key '{method.routing_key}' diferente do evento "
                      f"assinado '{envelope.event}': DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        # Valida a assinatura antes do processamento.
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
            log.exception(f"erro ao processar {envelope.event}: evento DESCARTADO")
            canal.basic_nack(tag, requeue=False)
            return

        canal.basic_ack(tag)

    def handle(self, event: str, payload: dict) -> None:
        raise NotImplementedError

    # Atalho de publicacao
    def publish(self, exchange: str, routing_key: str, payload: dict) -> None:
        if self.publisher is None:
            raise RuntimeError(f"{self.name} foi criado com publica=False")
        self.publisher.publish(exchange, routing_key, payload)
