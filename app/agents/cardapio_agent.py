from pathlib import Path

from app.business_config import get_active_business_settings


class CardapioAgent:
    """Le o cardapio de arquivo texto para uso no contexto da LLM."""

    def __init__(self, cardapio_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent
        self.cardapio_path = cardapio_path or (base_dir / "cardapio.txt")

    def get_cardapio(self) -> str:
        business = get_active_business_settings()
        dynamic_menu = business.cardapio_as_text()
        if dynamic_menu:
            return dynamic_menu
        if not self.cardapio_path.exists():
            return ''
        return self.cardapio_path.read_text(encoding="utf-8").strip()
