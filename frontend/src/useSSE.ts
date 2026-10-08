import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { EVENTOS, type NomeEvento, type Pedido } from './types'

/**
 * Mantem a conexao SSE com o API Gateway.
 *
 * O EventSource e aberto no mount, ANTES de qualquer pedido existir: se
 * abrissemos depois do POST, os primeiros eventos da cadeia (que chegam em
 * milissegundos) se perderiam. O proprio EventSource reconecta sozinho
 * quando a conexao cai.
 */
export function useSSE(
  clienteId: string,
  aoReceber: (evento: NomeEvento, pedido: Pedido) => void,
) {
  const [conectado, setConectado] = useState(false)
  // Guardamos o callback numa ref para nao reabrir a conexao a cada render.
  const callback = useRef(aoReceber)
  callback.current = aoReceber

  useEffect(() => {
    const fonte = new EventSource(api.urlEventos(clienteId))

    fonte.onopen = () => setConectado(true)
    fonte.onerror = () => setConectado(false)

    for (const nome of EVENTOS) {
      fonte.addEventListener(nome, (evento) => {
        setConectado(true)
        callback.current(nome, JSON.parse((evento as MessageEvent).data))
      })
    }

    return () => fonte.close()
  }, [clienteId])

  return conectado
}
