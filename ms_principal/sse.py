"""Barramento SSE: leva os eventos da thread do pika ate o navegador.

Duas regras governam este arquivo:

1. O registro de assinantes e tocado APENAS pela thread do event loop. A
   thread do pika nunca mexe nele diretamente -- ela agenda o fan-out com
   call_soon_threadsafe, e o fan-out roda no loop. Por isso nao ha lock aqui.

2. As filas sao asyncio.Queue, nao queue.Queue. Um gerador sincrono em
   StreamingResponse ocuparia uma thread do pool do anyio (40 no total,
   compartilhadas com todas as rotas `def`) durante TODA a conexao aberta:
   40 abas travariam a API inteira, e um `get()` bloqueado nao e cancelavel,
   entao cada aba fechada vazaria uma thread para sempre.
"""

import asyncio
import json
import logging

log = logging.getLogger(__name__)

# Por assinante. Se o navegador nao consome no ritmo, descartamos o evento
# mais antigo em vez de segurar a thread do pika.
TAMANHO_FILA = 100

# Comentario SSE periodico; segura proxies e deteta cliente sumido.
INTERVALO_PING = 15.0


class Barramento:

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._assinantes: dict[str, set[asyncio.Queue]] = {}

    def ligar(self, loop: asyncio.AbstractEventLoop) -> None:
        """Guarda o loop do uvicorn. Chamado no lifespan."""
        self._loop = loop

    # --- lado do event loop ---

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
        """Sentinela em todas as filas, para o shutdown do uvicorn nao travar.

        Um stream SSE nunca termina sozinho; sem isso o graceful shutdown
        esperaria por ele indefinidamente.
        """
        for filas in list(self._assinantes.values()):
            for fila in filas:
                self._enfileirar(fila, None)

    # --- lado da thread do pika ---

    def publicar(self, cliente: str, evento: str, dados: dict) -> None:
        if self._loop is None:
            log.warning(f"SSE ainda nao esta no ar; evento {evento} descartado")
            return
        # call_soon_threadsafe nunca bloqueia: a thread do pika nao fica presa
        # esperando o navegador.
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
                fila.get_nowait()  # descarta o mais antigo e abre espaco
                fila.put_nowait(mensagem)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass


BARRAMENTO = Barramento()


async def stream(cliente: str):
    """Gerador do text/event-stream de um cliente."""
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
        # Roda tambem quando o navegador fecha a aba: o cancelamento do
        # gerador async passa por aqui, entao nenhum assinante fica orfao.
        BARRAMENTO.cancelar(cliente, fila)
