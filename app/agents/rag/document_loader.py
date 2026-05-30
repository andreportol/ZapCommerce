from pathlib import Path


class DocumentLoader:
    """Carrega documentos texto para uso no RAG simples."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8").strip()
