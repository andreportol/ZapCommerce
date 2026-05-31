from dataclasses import asdict, dataclass, field

from django.db import transaction

from app.models import Cliente, Conversa, EstadoConversa


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
    FORA_HORARIO = "fora_horario"
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


def _build_default_state(telefone: str) -> ConversationState:
    return ConversationState(telefone=(telefone or "").strip())


def _get_or_create_state_model(telefone: str) -> EstadoConversa:
    phone = (telefone or "").strip()
    if not phone:
        raise ValueError("telefone obrigatorio")

    with transaction.atomic():
        cliente, _ = Cliente.objects.get_or_create(telefone=phone)
        conversa = (
            Conversa.objects.select_for_update()
            .filter(cliente=cliente)
            .exclude(status=Conversa.Status.FINALIZADA)
            .order_by("-atualizado_em")
            .first()
        )
        if conversa is None:
            conversa = Conversa.objects.create(cliente=cliente, status=Conversa.Status.IA)
        state, _ = EstadoConversa.objects.get_or_create(conversa=conversa)
    return state


def _to_dataclass(state_model: EstadoConversa) -> ConversationState:
    return ConversationState(
        telefone=state_model.conversa.cliente.telefone,
        status_atendimento=state_model.status_atendimento,
        ultima_intencao=state_model.ultima_intencao,
        itens_pedido=list(state_model.itens_pedido or []),
        itens_pendentes=list(state_model.itens_pendentes or []),
        tipo_entrega=state_model.tipo_entrega,
        produto=state_model.produto,
        quantidade=state_model.quantidade,
        valor_unitario=state_model.valor_unitario,
        valor_total=state_model.valor_total,
        endereco=state_model.endereco,
        forma_pagamento=state_model.forma_pagamento,
        aguardando_resposta=state_model.aguardando_resposta,
    )


def get_or_create_state(telefone: str) -> ConversationState:
    state_model = _get_or_create_state_model(telefone)
    return _to_dataclass(state_model)


def update_state(telefone: str, **fields) -> ConversationState:
    state_model = _get_or_create_state_model(telefone)
    valid_fields = set(ConversationState.__dataclass_fields__.keys())
    for key, value in fields.items():
        if key not in valid_fields:
            continue
        setattr(state_model, key, value)
    state_model.save()
    return _to_dataclass(state_model)


def reset_state(telefone: str) -> ConversationState:
    phone = (telefone or "").strip()
    if not phone:
        raise ValueError("telefone obrigatorio")
    state_model = _get_or_create_state_model(phone)
    default_state = _build_default_state(phone)
    for key, value in asdict(default_state).items():
        if key == "telefone":
            continue
        setattr(state_model, key, value)
    state_model.save()
    return _to_dataclass(state_model)


def delete_state(telefone: str) -> None:
    phone = (telefone or "").strip()
    if not phone:
        return
    EstadoConversa.objects.filter(conversa__cliente__telefone=phone).delete()


def clear_all_states() -> None:
    EstadoConversa.objects.all().update(
        status_atendimento=AtendimentoStatus.INICIO,
        ultima_intencao="",
        itens_pedido=[],
        itens_pendentes=[],
        tipo_entrega="",
        produto="",
        quantidade=0,
        valor_unitario=0.0,
        valor_total=0.0,
        endereco="",
        forma_pagamento="",
        aguardando_resposta="",
    )


def state_to_dict(telefone: str) -> dict:
    state = get_or_create_state(telefone)
    return asdict(state)
