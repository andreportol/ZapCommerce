from pathlib import Path

from app.business_config import (
    delivery_hours_summary,
    get_active_business_settings,
    order_hours_summary,
    owner_consultation_threshold,
    pickup_hours_summary,
)

DEFAULT_INSTRUCTIONS = (
    "Atenda com educacao, objetividade e clareza em portugues do Brasil. "
    "Quando faltar informacao, peca dados de forma simples."
)


class InstructionsAgent:
    """Le instrucoes de atendimento de arquivo texto."""

    def __init__(self, instructions_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent
        self.instructions_path = instructions_path or (base_dir / "instructions.txt")

    def get_instructions(self) -> str:
        if not self.instructions_path.exists():
            return self._append_dynamic_context(DEFAULT_INSTRUCTIONS)

        content = self.instructions_path.read_text(encoding="utf-8").strip()
        return self._append_dynamic_context(content or DEFAULT_INSTRUCTIONS)

    def _append_dynamic_context(self, content: str) -> str:
        business = get_active_business_settings()
        dynamic_lines = [
            '## Contexto dinamico do negocio',
            f'Pedidos/encomendas: {order_hours_summary(business)}.',
            f'Entregas: {delivery_hours_summary(business)}.',
            f'Retiradas: {pickup_hours_summary(business)}.',
            f'Pedidos acima de {owner_consultation_threshold(business)} pessoas exigem consulta da proprietaria.',
        ]
        if business.aceita_entrega and not business.aceita_retirada_local:
            dynamic_lines.append('No momento a operacao esta configurada apenas para entrega.')
        elif business.aceita_retirada_local and not business.aceita_entrega:
            dynamic_lines.append('No momento a operacao esta configurada apenas para retirada no local.')
        return f"{content}\n\n" + "\n".join(dynamic_lines)
