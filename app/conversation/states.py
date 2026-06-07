from enum import Enum


class AwaitingResponse(str, Enum):
    MENU_PRINCIPAL = "menu_principal"
    PRODUTO = "produto"
    QUANTIDADE = "quantidade"
    COMPLEMENTO = "complemento"
    QUANTIDADE_COMPLEMENTO = "quantidade_complemento"
    MAIS_COMPLEMENTOS = "mais_complementos"
    TIPO_ENTREGA = "tipo_entrega"
    ENDERECO = "endereco"
    NOME_CLIENTE = "nome_cliente"
    FORMA_PAGAMENTO = "forma_pagamento"
    COMPROVANTE = "comprovante"
    CONFERENCIA_PAGAMENTO = "conferencia_pagamento"
    CONFIRMACAO = "confirmacao"
    NOT_MAPPED = "not_mapped"


class ConversationStatus(str, Enum):
    INICIO = "inicio"
    AGUARDANDO_PRODUTO = "aguardando_produto"
    AGUARDANDO_QUANTIDADE = "aguardando_quantidade"
    AGUARDANDO_TIPO_ENTREGA = "aguardando_tipo_entrega"
    AGUARDANDO_ENDERECO = "aguardando_endereco"
    AGUARDANDO_NOME_CLIENTE = "aguardando_nome_cliente"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    AGUARDANDO_COMPROVANTE = "aguardando_comprovante"
    AGUARDANDO_CONFERENCIA_PAGAMENTO = "aguardando_conferencia_pagamento"
    AGUARDANDO_CONFIRMACAO = "aguardando_confirmacao"
