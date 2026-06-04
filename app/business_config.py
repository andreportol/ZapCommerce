from dataclasses import dataclass, field
from datetime import date, datetime, time

from django.utils import timezone

from .models import ConfiguracaoMarmitaria, DiaSemana

DAY_ORDER = [
    DiaSemana.SEGUNDA,
    DiaSemana.TERCA,
    DiaSemana.QUARTA,
    DiaSemana.QUINTA,
    DiaSemana.SEXTA,
    DiaSemana.SABADO,
    DiaSemana.DOMINGO,
]

DAY_INDEX_MAP = {
    0: DiaSemana.SEGUNDA,
    1: DiaSemana.TERCA,
    2: DiaSemana.QUARTA,
    3: DiaSemana.QUINTA,
    4: DiaSemana.SEXTA,
    5: DiaSemana.SABADO,
    6: DiaSemana.DOMINGO,
}

DAY_DISPLAY_MAP = {
    DiaSemana.SEGUNDA: 'segunda-feira',
    DiaSemana.TERCA: 'terça-feira',
    DiaSemana.QUARTA: 'quarta-feira',
    DiaSemana.QUINTA: 'quinta-feira',
    DiaSemana.SEXTA: 'sexta-feira',
    DiaSemana.SABADO: 'sábado',
    DiaSemana.DOMINGO: 'domingo',
}

DEFAULT_ORDER_OPEN = time(9, 0)
DEFAULT_ORDER_CLOSE = time(12, 30)
DEFAULT_DELIVERY_OPEN = time(11, 0)
DEFAULT_DELIVERY_CLOSE = time(13, 0)
DEFAULT_PICKUP_OPEN = time(11, 0)
DEFAULT_PICKUP_CLOSE = time(13, 0)


@dataclass(frozen=True)
class DaySchedule:
    dia_semana: str
    fechado: bool = False
    abre_pedidos: time | None = None
    fecha_pedidos: time | None = None
    abre_entregas: time | None = None
    fecha_entregas: time | None = None
    abre_retiradas: time | None = None
    fecha_retiradas: time | None = None

    def is_open_for_orders(self, when: datetime) -> bool:
        if self.fechado or not self.abre_pedidos or not self.fecha_pedidos:
            return False
        now_time = when.timetz().replace(tzinfo=None)
        return self.abre_pedidos <= now_time <= self.fecha_pedidos


@dataclass(frozen=True)
class BusinessSettings:
    nome_empresa: str = 'Marmitaria Adriana'
    telefone_atendimento: str = ''
    chave_pix: str = ''
    horario_funcionamento: str = ''
    taxa_entrega_padrao: float = 0.0
    aceita_pedidos: bool = True
    aceita_entrega: bool = True
    aceita_retirada_local: bool = True
    pedido_maximo_sem_consulta: int = 5
    endereco_retirada: str = ''
    mensagem_boas_vindas: str = ''
    mensagem_fora_horario: str = ''
    schedules: dict[str, DaySchedule] = field(default_factory=dict)
    menus: dict[str, str] = field(default_factory=dict)

    def schedule_for_day(self, day_key: str) -> DaySchedule | None:
        return self.schedules.get(day_key)

    def cardapio_as_text(self) -> str:
        sections: list[str] = []
        for day_key in DAY_ORDER:
            menu = (self.menus.get(day_key) or '').strip()
            if not menu:
                continue
            sections.append(f'## {day_key}\n{menu}')
        return '\n'.join(sections).strip()


def get_active_business_settings() -> BusinessSettings:
    try:
        config = (
            ConfiguracaoMarmitaria.objects.filter(ativo=True)
            .prefetch_related('horarios_funcionamento', 'cardapios_dia')
            .first()
        )
    except Exception:
        return default_business_settings()

    if config is None:
        return default_business_settings()

    db_schedules = list(config.horarios_funcionamento.all())
    schedules = _build_schedules_from_db(db_schedules) if db_schedules else default_business_settings().schedules
    menus = {
        item.dia_semana: (item.descricao or '').strip()
        for item in config.cardapios_dia.all()
        if item.ativo and (item.descricao or '').strip()
    }
    return BusinessSettings(
        nome_empresa=config.nome_empresa,
        telefone_atendimento=config.telefone_atendimento,
        chave_pix=config.chave_pix,
        horario_funcionamento=config.horario_funcionamento,
        taxa_entrega_padrao=float(config.taxa_entrega_padrao),
        aceita_pedidos=config.aceita_pedidos,
        aceita_entrega=config.aceita_entrega,
        aceita_retirada_local=config.aceita_retirada_local,
        pedido_maximo_sem_consulta=int(config.pedido_maximo_sem_consulta),
        endereco_retirada=config.endereco_retirada,
        mensagem_boas_vindas=config.mensagem_boas_vindas,
        mensagem_fora_horario=config.mensagem_fora_horario,
        schedules=schedules,
        menus=menus,
    )


def default_business_settings() -> BusinessSettings:
    schedules: dict[str, DaySchedule] = {}
    for day_key in DAY_ORDER:
        schedules[day_key] = DaySchedule(
            dia_semana=day_key,
            fechado=day_key == DiaSemana.DOMINGO,
            abre_pedidos=None if day_key == DiaSemana.DOMINGO else DEFAULT_ORDER_OPEN,
            fecha_pedidos=None if day_key == DiaSemana.DOMINGO else DEFAULT_ORDER_CLOSE,
            abre_entregas=None if day_key == DiaSemana.DOMINGO else DEFAULT_DELIVERY_OPEN,
            fecha_entregas=None if day_key == DiaSemana.DOMINGO else DEFAULT_DELIVERY_CLOSE,
            abre_retiradas=None if day_key == DiaSemana.DOMINGO else DEFAULT_PICKUP_OPEN,
            fecha_retiradas=None if day_key == DiaSemana.DOMINGO else DEFAULT_PICKUP_CLOSE,
        )
    return BusinessSettings(
        horario_funcionamento='segunda a sábado, das 9h às 12h30',
        schedules=schedules,
    )


def current_weekday_key(target_date: date | None = None) -> str:
    base_date = target_date or timezone.localdate()
    return DAY_INDEX_MAP[base_date.weekday()]


def is_open_for_orders(when: datetime | None = None, business: BusinessSettings | None = None) -> bool:
    active_business = business or get_active_business_settings()
    if not active_business.aceita_pedidos:
        return False

    current_dt = when or timezone.localtime()
    day_key = DAY_INDEX_MAP[current_dt.weekday()]
    schedule = active_business.schedule_for_day(day_key)
    if schedule is None:
        return False
    return schedule.is_open_for_orders(current_dt)


def order_hours_summary(business: BusinessSettings | None = None) -> str:
    return _window_summary('pedido', business or get_active_business_settings())


def delivery_hours_summary(business: BusinessSettings | None = None) -> str:
    active_business = business or get_active_business_settings()
    if not active_business.aceita_entrega:
        return 'entrega desativada'
    return _window_summary('entrega', active_business)


def pickup_hours_summary(business: BusinessSettings | None = None) -> str:
    active_business = business or get_active_business_settings()
    if not active_business.aceita_retirada_local:
        return 'retirada desativada'
    return _window_summary('retirada', active_business)


def order_hours_for_day(day_key: str, business: BusinessSettings | None = None) -> str:
    active_business = business or get_active_business_settings()
    schedule = active_business.schedule_for_day(day_key)
    if not schedule or schedule.fechado or not schedule.abre_pedidos or not schedule.fecha_pedidos:
        return ''
    return f'entre {format_time_br(schedule.abre_pedidos)} e {format_time_br(schedule.fecha_pedidos)}'


def owner_consultation_threshold(business: BusinessSettings | None = None) -> int:
    active_business = business or get_active_business_settings()
    return max(1, int(active_business.pedido_maximo_sem_consulta or 1))


def owner_consultation_message(business: BusinessSettings | None = None) -> str:
    threshold = owner_consultation_threshold(business)
    return (
        f'Para pedidos acima de {threshold} pessoas, preciso consultar a proprietária '
        'para confirmar o valor certinho.'
    )


def format_time_br(value: time | None) -> str:
    if value is None:
        return ''
    if value.minute == 0:
        return f'{value.hour}h'
    return f'{value.hour}h{value.minute:02d}'


def format_day_display(day_key: str) -> str:
    return DAY_DISPLAY_MAP.get(day_key, day_key)


def _build_schedules_from_db(items: list) -> dict[str, DaySchedule]:
    schedules: dict[str, DaySchedule] = {
        day_key: DaySchedule(dia_semana=day_key, fechado=True)
        for day_key in DAY_ORDER
    }
    for item in items:
        schedules[item.dia_semana] = DaySchedule(
            dia_semana=item.dia_semana,
            fechado=bool(item.fechado),
            abre_pedidos=item.abre_pedidos,
            fecha_pedidos=item.fecha_pedidos,
            abre_entregas=item.abre_entregas,
            fecha_entregas=item.fecha_entregas,
            abre_retiradas=item.abre_retiradas,
            fecha_retiradas=item.fecha_retiradas,
        )
    return schedules


def _window_summary(window_kind: str, business: BusinessSettings) -> str:
    field_names = {
        'pedido': ('abre_pedidos', 'fecha_pedidos'),
        'entrega': ('abre_entregas', 'fecha_entregas'),
        'retirada': ('abre_retiradas', 'fecha_retiradas'),
    }
    start_field, end_field = field_names[window_kind]
    open_days: list[tuple[str, time, time]] = []
    for day_key in DAY_ORDER:
        schedule = business.schedule_for_day(day_key)
        if not schedule or schedule.fechado:
            continue
        start_value = getattr(schedule, start_field)
        end_value = getattr(schedule, end_field)
        if start_value and end_value:
            open_days.append((day_key, start_value, end_value))

    if not open_days:
        return 'sem horario configurado'

    unique_ranges = {(start_value, end_value) for _, start_value, end_value in open_days}
    if len(unique_ranges) == 1:
        start_value, end_value = next(iter(unique_ranges))
        day_labels = [day_key for day_key, _, _ in open_days]
        return f'{_compact_day_range(day_labels)}, das {format_time_br(start_value)} às {format_time_br(end_value)}'

    return '; '.join(
        f'{format_day_display(day_key)}: {format_time_br(start_value)} às {format_time_br(end_value)}'
        for day_key, start_value, end_value in open_days
    )


def _compact_day_range(day_keys: list[str]) -> str:
    if day_keys == DAY_ORDER[:-1]:
        return 'segunda a sábado'
    if day_keys == DAY_ORDER:
        return 'todos os dias'
    if len(day_keys) == 1:
        return format_day_display(day_keys[0])
    return ', '.join(format_day_display(day_key) for day_key in day_keys)
