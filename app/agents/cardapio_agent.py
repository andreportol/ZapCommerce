from pathlib import Path


class CardapioAgent:
    """Le o cardapio de arquivo texto para uso no contexto da LLM."""

    def __init__(self, cardapio_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent
        self.cardapio_path = cardapio_path or (base_dir / "cardapio.txt")

    def get_cardapio(self) -> str:
        if not self.cardapio_path.exists():
            return ""
        return self.cardapio_path.read_text(encoding="utf-8").strip()
