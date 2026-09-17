from enum import StrEnum


class Evento(StrEnum):

    PEDIDO_CRIADO = "pedido.criado"
    PEDIDO_EXCLUIDO = "pedido.excluido"
    PEDIDO_ESTOQUE_OK = "pedido.estoque_ok"
    ESTOQUE_INDISPONIVEL = "estoque.indisponivel"
    PAGAMENTO_APROVADO = "pagamento.aprovado"
    PAGAMENTO_RECUSADO = "pagamento.recusado"
    PEDIDO_ENVIADO = "pedido.enviado"
