import asyncio
import json
import logging

log = logging.getLogger(__name__)

TAMANHO_FILA = 100
INTERVALO_PING = 15.0


class Barramento:

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._assinantes: dict[str, set[asyncio.Queue]] = {}

    def ligar(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # --- event loop ---

    def inscrever(self, cliente: str) -> asyncio.Queue:
        fila: asyncio.Queue = asyncio.Queue(maxsize=TAMANHO_FILA)
        self._assinantes.setdefault(cliente, set()).add(fila)
        log.info(f"SSE: {cliente} conectou "
                 f"({len(self._assinantes[cliente])} conexao(oes))")
        return fila

    def cancelar(self, cliente: str, fila: asyncio.Queue) -> None:
        filas = self._assinantes.get(cliente)
        if not filas:
            return
        filas.discard(fila)
        if not filas:
            del self._assinantes[cliente]
        log.info(f"SSE: {cliente} desconectou")

    def encerrar_todos(self) -> None:
        for filas in list(self._assinantes.values()):
            for fila in filas:
                self._enfileirar(fila, None)

    # --- thread do pika ---

    def publicar(self, cliente: str, evento: str, dados: dict) -> None:
        if self._loop is None:
            log.warning(f"SSE ainda nao esta no ar; evento {evento} descartado")
            return
        self._loop.call_soon_threadsafe(self._entregar, cliente, evento, dados)

    def _entregar(self, cliente: str, evento: str, dados: dict) -> None:
        mensagem = f"event: {evento}\ndata: {json.dumps(dados)}\n\n"
        for fila in self._assinantes.get(cliente, ()):
            self._enfileirar(fila, mensagem)

    @staticmethod
    def _enfileirar(fila: asyncio.Queue, mensagem) -> None:
        try:
            fila.put_nowait(mensagem)
        except asyncio.QueueFull:
            try:
                fila.get_nowait()
                fila.put_nowait(mensagem)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass


BARRAMENTO = Barramento()


async def stream(cliente: str):
    fila = BARRAMENTO.inscrever(cliente)
    try:
        yield ": conectado\n\n"
        while True:
            try:
                mensagem = await asyncio.wait_for(fila.get(), timeout=INTERVALO_PING)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if mensagem is None:  # sentinela de shutdown
                return
            yield mensagem
    finally:
        BARRAMENTO.cancelar(cliente, fila)
