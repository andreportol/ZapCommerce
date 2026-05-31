from dataclasses import asdict, dataclass, field


@dataclass
class ConversationState:
    telefone: str
    status_atendimento: str = "inicio"
    ultima_intencao: str = ""
    itens_pedido: list[dict] = field(default_factory=list)
    itens_pendentes: list[dict] = field(default_factory=list)
    tipo_entrega: str = ""
    produto: str = ""
    quantidade: int = 0
    valor_unitario: float = 0.0
    valor_total: float = 0.0
    endereco: str = ""
    forma_pagamento: str = ""
    aguardando_resposta: str = ""


class AtendimentoStatus:
    INICIO = "inicio"
    CONSULTANDO_CARDAPIO = "consultando_cardapio"
    AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO = "aguardando_confirmacao_fazer_pedido"
    FAZENDO_PEDIDO = "fazendo_pedido"
    AGUARDANDO_TIPO_ENTREGA = "aguardando_tipo_entrega"
    AGUARDANDO_CONFIRMACAO_ITEM = "aguardando_confirmacao_item"
    AGUARDANDO_PRODUTO = "aguardando_produto"
    AGUARDANDO_PESSOAS_MARMITA = "aguardando_pessoas_marmita"
    AGUARDANDO_QUANTIDADE = "aguardando_quantidade"
    AGUARDANDO_ENDERECO = "aguardando_endereco"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    AGUARDANDO_COMPROVANTE = "aguardando_comprovante"
    AGUARDANDO_CONFERENCIA_PAGAMENTO = "aguardando_conferencia_pagamento"
    AGUARDANDO_CONFIRMACAO = "aguardando_confirmacao"
    ENCAMINHAR_ATENDENTE = "encaminhar_atendente"


_CONVERSATION_MEMORY: dict[str, ConversationState] = {}


def get_or_create_state(telefone: str) -> ConversationState:
    phone = (telefone or "").strip()
    if not phone:
        raise ValueError("telefone obrigatorio")
    state = _CONVERSATION_MEMORY.get(phone)
    if state is None:
        state = ConversationState(telefone=phone)
        _CONVERSATION_MEMORY[phone] = state
    return state


def update_state(telefone: str, **fields) -> ConversationState:
    state = get_or_create_state(telefone)
    valid_fields = set(ConversationState.__dataclass_fields__.keys())
    for key, value in fields.items():
        if key not in valid_fields:
            continue
        setattr(state, key, value)
    return state


def reset_state(telefone: str) -> ConversationState:
    phone = (telefone or "").strip()
    if not phone:
        raise ValueError("telefone obrigatorio")
    state = ConversationState(telefone=phone)
    _CONVERSATION_MEMORY[phone] = state
    return state


def delete_state(telefone: str) -> None:
    phone = (telefone or "").strip()
    if phone:
        _CONVERSATION_MEMORY.pop(phone, None)


def clear_all_states() -> None:
    _CONVERSATION_MEMORY.clear()


def state_to_dict(telefone: str) -> dict:
    state = get_or_create_state(telefone)
    return asdict(state)
