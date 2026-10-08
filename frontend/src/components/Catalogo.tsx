import { useState } from 'react'
import type { Produto } from '../types'

interface Props {
  produtos: Produto[]
  aoFinalizar: (itens: { produtoId: string; quantidade: number }[]) => void
}

const moeda = (v: number) =>
  v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

export function Catalogo({ produtos, aoFinalizar }: Props) {
  const [carrinho, setCarrinho] = useState<Record<string, number>>({})

  function mudar(id: string, delta: number, maximo: number) {
    setCarrinho((atual) => {
      const quantidade = Math.min(maximo, Math.max(0, (atual[id] ?? 0) + delta))
      const copia = { ...atual }
      if (quantidade === 0) delete copia[id]
      else copia[id] = quantidade
      return copia
    })
  }

  const itens = Object.entries(carrinho).map(([produtoId, quantidade]) => ({
    produtoId,
    quantidade,
  }))

  const total = itens.reduce((soma, item) => {
    const produto = produtos.find((p) => p.id === item.produtoId)
    return soma + (produto?.preco ?? 0) * item.quantidade
  }, 0)

  function finalizar() {
    aoFinalizar(itens)
    setCarrinho({})
  }

  return (
    <section className="cartao">
      <h2>Catalogo</h2>
      {produtos.length === 0 ? (
        <p className="vazio">Carregando produtos...</p>
      ) : (
        <ul className="produtos">
          {produtos.map((p) => {
            const noCarrinho = carrinho[p.id] ?? 0
            const esgotado = p.quantidade === 0
            return (
              <li key={p.id} className={esgotado ? 'esgotado' : ''}>
                <div className="info">
                  <strong>{p.nome}</strong>
                  <span className="meta">
                    {p.id} &middot; categoria {p.categoria} &middot;{' '}
                    {esgotado ? 'sem estoque' : `${p.quantidade} em estoque`}
                  </span>
                </div>
                <div className="preco">{moeda(p.preco)}</div>
                <div className="contador">
                  <button
                    onClick={() => mudar(p.id, -1, p.quantidade)}
                    disabled={noCarrinho === 0}
                    aria-label={`Remover ${p.nome}`}
                  >
                    &minus;
                  </button>
                  <span>{noCarrinho}</span>
                  <button
                    onClick={() => mudar(p.id, +1, p.quantidade)}
                    disabled={noCarrinho >= p.quantidade}
                    aria-label={`Adicionar ${p.nome}`}
                  >
                    +
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <footer className="rodape-carrinho">
        <span>
          {itens.length === 0
            ? 'Carrinho vazio'
            : `${itens.length} produto(s) - ${moeda(total)}`}
        </span>
        <button className="primario" onClick={finalizar} disabled={itens.length === 0}>
          Finalizar pedido
        </button>
      </footer>
    </section>
  )
}
