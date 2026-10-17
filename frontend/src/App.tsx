import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { Catalogo } from './components/Catalogo'
import { Pedidos } from './components/Pedidos'
import { Promocoes } from './components/Promocoes'
import { useSSE } from './useSSE'
import type { LinhaLog, NomeEvento, Pedido, Produto } from './types'

/** Identidade do navegador: so ele recebe os eventos dos seus pedidos. */
function obterClienteId(): string {
  const guardado = localStorage.getItem('clienteId')
  if (guardado) return guardado
  const novo = `cli-${Math.random().toString(36).slice(2, 8)}`
  localStorage.setItem('clienteId', novo)
  return novo
}

export default function App() {
  const [clienteId] = useState(obterClienteId)
  const [produtos, setProdutos] = useState<Produto[]>([])
  const [pedidos, setPedidos] = useState<Pedido[]>([])
  const [log, setLog] = useState<LinhaLog[]>([])
  const [erro, setErro] = useState('')
  const proximoId = useRef(0)

  const carregarProdutos = useCallback(async () => {
    try {
      setProdutos(await api.produtos())
      setErro('')
    } catch (e) {
      setErro(`Nao foi possivel listar os produtos: ${(e as Error).message}`)
    }
  }, [])

  useEffect(() => {
    carregarProdutos()
    api.pedidos(clienteId).then(setPedidos).catch(() => {})
  }, [carregarProdutos, clienteId])

  const aoReceberEvento = useCallback(
    (evento: NomeEvento, pedido: Pedido) => {
      setPedidos((atuais) => {
        const outros = atuais.filter((p) => p.pedidoId !== pedido.pedidoId)
        return [...outros, pedido].sort((a, b) =>
          a.pedidoId.localeCompare(b.pedidoId),
        )
      })

      setLog((atuais) =>
        [
          {
            id: proximoId.current++,
            evento,
            pedidoId: pedido.pedidoId,
            hora: new Date().toLocaleTimeString('pt-BR'),
          },
          ...atuais,
        ].slice(0, 40),
      )

      // Toda mudanca de estado mexe no estoque ou o libera de volta.
      carregarProdutos()

      if (evento === 'pagamento.pendente' && pedido.checkoutUrl) {
        // Pode ser bloqueado: nao veio de um clique do usuario. Por isso o
        // botao "Pagar agora" fica visivel no card do pedido.
        window.open(pedido.checkoutUrl, '_blank', 'noopener')
      }
    },
    [carregarProdutos],
  )

  const conectado = useSSE(clienteId, aoReceberEvento)

  async function criarPedido(itens: { produtoId: string; quantidade: number }[]) {
    try {
      const pedido = await api.criarPedido(clienteId, itens)
      setPedidos((atuais) => [...atuais, pedido])
      setErro('')
    } catch (e) {
      setErro(`Falha ao criar o pedido: ${(e as Error).message}`)
    }
  }

  async function excluirPedido(pedidoId: string) {
    try {
      await api.excluirPedido(pedidoId)
      setErro('')
    } catch (e) {
      setErro(`Falha ao excluir: ${(e as Error).message}`)
    }
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>E-commerce distribuido</h1>
          <p className="sub">
            REST + SSE sobre RabbitMQ &middot; cliente <code>{clienteId}</code>
          </p>
        </div>
        <span className={`selo ${conectado ? 'on' : 'off'}`}>
          {conectado ? 'SSE conectado' : 'SSE desconectado'}
        </span>
      </header>

      {erro && <p className="erro">{erro}</p>}

      <main>
        <div className="coluna">
          <Catalogo produtos={produtos} aoFinalizar={criarPedido} />
          <Promocoes />
        </div>
        <div className="coluna">
          <Pedidos pedidos={pedidos} aoExcluir={excluirPedido} />
          <section className="cartao">
            <h2>Eventos recebidos (SSE)</h2>
            {log.length === 0 ? (
              <p className="vazio">Nenhum evento ainda.</p>
            ) : (
              <ul className="log">
                {log.map((linha) => (
                  <li key={linha.id}>
                    <span className="hora">{linha.hora}</span>
                    <code className={`ev ${linha.evento.split('.')[0]}`}>
                      {linha.evento}
                    </code>
                    <span className="pid">{linha.pedidoId}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}
