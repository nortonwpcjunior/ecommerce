"""Nomes dos eventos do sistema, em um unico lugar.

As routing keys apareciam repetidas como string literal solta por todo o
projeto (`pedido.criado` 13 vezes, `pedido.estoque_ok` e `pagamento.aprovado`
8 cada). Um erro de digitacao em uma delas e um bug silencioso: o evento sai
numa chave que nenhuma fila escuta, ou um binding nunca casa, e nada estoura
-- o pedido apenas para de andar, sem erro nos logs.

`Evento` e um StrEnum, entao cada membro E uma str: serve direto como routing
key do pika e como valor do campo `event` do envelope. A serializacao
canonica produz exatamente os mesmos bytes de antes, portanto a assinatura
nao muda e um processo que ainda use as strings cruas continua interoperando.
"""

from enum import StrEnum


class Evento(StrEnum):
    """Routing keys da exchange eCommerce (direct, casamento exato)."""

    PEDIDO_CRIADO = "pedido.criado"
    PEDIDO_EXCLUIDO = "pedido.excluido"
    PEDIDO_ESTOQUE_OK = "pedido.estoque_ok"
    ESTOQUE_INDISPONIVEL = "estoque.indisponivel"
    PAGAMENTO_APROVADO = "pagamento.aprovado"
    PAGAMENTO_RECUSADO = "pagamento.recusado"
    PEDIDO_ENVIADO = "pedido.enviado"


# As promocoes usam routing key hierarquica com a categoria no fim, montada em
# tempo de execucao -- nao cabe num enum fechado, porque a categoria vem do
# catalogo e nao do codigo.
PROMOCAO_CATEGORIA = "promocao.categoria"

# Binding do C2: '*' casa exatamente uma palavra, cobrindo qualquer categoria.
PROMOCAO_TODAS = f"{PROMOCAO_CATEGORIA}.*"


def promocao_de(categoria: str) -> str:
    """Routing key de promocao de uma categoria: promocao.categoria.A."""
    return f"{PROMOCAO_CATEGORIA}.{categoria}"
