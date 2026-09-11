"""Catalogo de produtos (dado estatico compartilhado).

Nao e uma chamada entre processos: e uma tabela de referencia que cada
microsservico carrega localmente, como um arquivo de configuracao. O ESTOQUE
(quantidades) vive apenas dentro do ms_estoque; aqui ficam somente os dados
cadastrais do produto.
"""

PRODUTOS = {
    "P1": {"nome": "Notebook 14\"",     "categoria": "A", "preco": 4200.00},
    "P2": {"nome": "Mouse sem fio",     "categoria": "A", "preco": 149.90},
    "P3": {"nome": "Teclado mecanico",  "categoria": "B", "preco": 389.00},
    "P4": {"nome": "Monitor 27\"",      "categoria": "B", "preco": 1899.00},
    "P5": {"nome": "Cadeira ergonomica", "categoria": "C", "preco": 1250.00},
    "P6": {"nome": "Headset USB",       "categoria": "C", "preco": 279.00},
}

CATEGORIAS = ("A", "B", "C")


def por_categoria(categoria: str):
    return {pid: p for pid, p in PRODUTOS.items() if p["categoria"] == categoria}
