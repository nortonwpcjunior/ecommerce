import type { Pedido, Produto } from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function json<T>(resposta: Response): Promise<T> {
  if (!resposta.ok) {
    let detalhe = `HTTP ${resposta.status}`
    try {
      const corpo = await resposta.json()
      if (corpo?.detail) detalhe = typeof corpo.detail === 'string'
        ? corpo.detail
        : JSON.stringify(corpo.detail)
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new Error(detalhe)
  }
  return resposta.json() as Promise<T>
}

export const api = {
  urlEventos: (clienteId: string) =>
    `${BASE}/api/eventos/${encodeURIComponent(clienteId)}`,

  produtos: () => fetch(`${BASE}/api/produtos`).then(json<Produto[]>),

  categorias: () => fetch(`${BASE}/api/categorias`).then(json<string[]>),

  pedidos: (clienteId: string) =>
    fetch(`${BASE}/api/pedidos?clienteId=${encodeURIComponent(clienteId)}`)
      .then(json<Pedido[]>),

  criarPedido: (clienteId: string, itens: { produtoId: string; quantidade: number }[]) =>
    fetch(`${BASE}/api/pedidos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clienteId, itens }),
    }).then(json<Pedido>),

  excluirPedido: (pedidoId: string) =>
    fetch(`${BASE}/api/pedidos/${pedidoId}`, { method: 'DELETE' }).then(json<Pedido>),

  registrarInteresse: (email: string, categorias: string[]) =>
    fetch(`${BASE}/api/interesses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, categorias }),
    }).then(json<{ email: string; categorias: string[] }>),

  cancelarInteresse: (email: string) =>
    fetch(`${BASE}/api/interesses?email=${encodeURIComponent(email)}`, {
      method: 'DELETE',
    }).then(json<{ email: string }>),
}
