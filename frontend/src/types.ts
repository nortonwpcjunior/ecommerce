export interface Produto {
  id: string
  nome: string
  categoria: string
  preco: number
  quantidade: number
}

export interface ItemPedido {
  produtoId: string
  quantidade: number
}

export interface Pedido {
  pedidoId: string
  cliente: string
  itens: ItemPedido[]
  total: number
  status: string
  rotulo: string
  detalhe: string
  checkoutUrl: string
}

/** Eventos que o gateway emite no canal SSE. */
export type NomeEvento =
  | 'pedido.criado'
  | 'pedido.estoque_ok'
  | 'estoque.indisponivel'
  | 'pagamento.pendente'
  | 'pagamento.aprovado'
  | 'pagamento.recusado'
  | 'pedido.enviado'
  | 'pedido.excluido'

export const EVENTOS: NomeEvento[] = [
  'pedido.criado',
  'pedido.estoque_ok',
  'estoque.indisponivel',
  'pagamento.pendente',
  'pagamento.aprovado',
  'pagamento.recusado',
  'pedido.enviado',
  'pedido.excluido',
]

export interface LinhaLog {
  id: number
  evento: NomeEvento
  pedidoId: string
  hora: string
}
