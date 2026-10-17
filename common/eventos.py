from enum import StrEnum


class Evento(StrEnum):

    INTERESSE_PROMOCAO = "interesse.promocao"
    PEDIDO_CRIADO = "pedido.criado"
    PEDIDO_EXCLUIDO = "pedido.excluido"
    PEDIDO_ESTOQUE_OK = "pedido.estoque_ok"
    ESTOQUE_INDISPONIVEL = "estoque.indisponivel"
    PAGAMENTO_PENDENTE = "pagamento.pendente"
    PAGAMENTO_APROVADO = "pagamento.aprovado"
    PAGAMENTO_RECUSADO = "pagamento.recusado"
    PEDIDO_ENVIADO = "pedido.enviado"
