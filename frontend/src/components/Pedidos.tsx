import type { Pedido } from '../types'

interface Props {
  pedidos: Pedido[]
  aoExcluir: (pedidoId: string) => void
}

const moeda = (v: number) =>
  v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

/** Agrupa os status em quatro cores: andamento, espera, sucesso e cancelado. */
function tom(status: string): string {
  if (status.startsWith('CANCELADO')) return 'ruim'
  if (status === 'ENVIADO') return 'bom'
  if (status === 'AGUARDANDO_PAGAMENTO') return 'espera'
  return 'andamento'
}

const EXCLUIVEIS = new Set([
  'AGUARDANDO_ESTOQUE',
  'ESTOQUE_RESERVADO',
  'AGUARDANDO_PAGAMENTO',
  'PAGAMENTO_APROVADO',
])

export function Pedidos({ pedidos, aoExcluir }: Props) {
  return (
    <section className="cartao">
      <h2>Meus pedidos</h2>
      {pedidos.length === 0 ? (
        <p className="vazio">Nenhum pedido ainda. Monte um no catalogo.</p>
      ) : (
        <ul className="pedidos">
          {pedidos.map((p) => (
            <li key={p.pedidoId} className={tom(p.status)}>
              <div className="linha">
                <code>{p.pedidoId}</code>
                <strong>{moeda(p.total)}</strong>
              </div>

              <div className="estado">
                <span className={`bolinha ${tom(p.status)}`} />
                {p.rotulo}
              </div>

              {p.detalhe && <p className="detalhe">{p.detalhe}</p>}

              <p className="itens">
                {p.itens.map((i) => `${i.quantidade}x ${i.produtoId}`).join(', ')}
              </p>

              <div className="acoes">
                {p.status === 'AGUARDANDO_PAGAMENTO' && p.checkoutUrl && (
                  // O window.open automatico costuma ser bloqueado pelo
                  // navegador porque nao parte de um clique. Este botao e a
                  // garantia de que da sempre para pagar.
                  <a
                    className="primario"
                    href={p.checkoutUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Pagar agora
                  </a>
                )}
                {EXCLUIVEIS.has(p.status) && (
                  <button className="perigo" onClick={() => aoExcluir(p.pedidoId)}>
                    Excluir
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
