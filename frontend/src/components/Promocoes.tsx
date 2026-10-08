import { useEffect, useState } from 'react'
import { api } from '../api'

export function Promocoes() {
  const [categorias, setCategorias] = useState<string[]>([])
  const [escolhidas, setEscolhidas] = useState<Set<string>>(new Set())
  const [email, setEmail] = useState(() => localStorage.getItem('email') ?? '')
  const [aviso, setAviso] = useState('')
  const [erro, setErro] = useState('')

  useEffect(() => {
    api.categorias().then(setCategorias).catch(() => setCategorias(['A', 'B', 'C']))
  }, [])

  function alternar(categoria: string) {
    setEscolhidas((atuais) => {
      const copia = new Set(atuais)
      if (copia.has(categoria)) copia.delete(categoria)
      else copia.add(categoria)
      return copia
    })
  }

  async function registrar() {
    setAviso('')
    setErro('')
    try {
      const r = await api.registrarInteresse(email, [...escolhidas])
      localStorage.setItem('email', email)
      setAviso(`Interesse registrado para as categorias ${r.categorias.join(', ')}.`)
    } catch (e) {
      setErro((e as Error).message)
    }
  }

  async function cancelar() {
    setAviso('')
    setErro('')
    try {
      await api.cancelarInteresse(email)
      setEscolhidas(new Set())
      setAviso('Interesse cancelado. Voce nao recebera mais ofertas.')
    } catch (e) {
      setErro((e as Error).message)
    }
  }

  const valido = email.includes('@') && email.includes('.')

  return (
    <section className="cartao">
      <h2>Ofertas por e-mail</h2>
      <p className="vazio">
        Escolha as categorias de interesse. O MS Promocoes dispara os e-mails
        pela API externa.
      </p>

      <label className="campo">
        <span>Seu e-mail</span>
        <input
          type="email"
          value={email}
          placeholder="voce@exemplo.com"
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>

      <div className="categorias">
        {categorias.map((c) => (
          <label key={c} className={escolhidas.has(c) ? 'marcada' : ''}>
            <input
              type="checkbox"
              checked={escolhidas.has(c)}
              onChange={() => alternar(c)}
            />
            Categoria {c}
          </label>
        ))}
      </div>

      <div className="acoes">
        <button
          className="primario"
          onClick={registrar}
          disabled={!valido || escolhidas.size === 0}
        >
          Quero receber
        </button>
        <button className="perigo" onClick={cancelar} disabled={!valido}>
          Cancelar inscricao
        </button>
      </div>

      {aviso && <p className="aviso">{aviso}</p>}
      {erro && <p className="erro">{erro}</p>}
    </section>
  )
}
