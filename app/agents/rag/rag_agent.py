from pathlib import Path

from .document_loader import DocumentLoader
from .retriever import KeywordRetriever
from .text_splitter import TextSplitter


class RagAgent:
    """RAG simples para recuperar trechos relevantes do instructions.txt."""

    def __init__(self, source_path: Path | str | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self.source_path = Path(source_path) if source_path else (base_dir / "instructions.txt")
        self.loader = DocumentLoader(self.source_path)
        self.splitter = TextSplitter()
        self._chunks: list[str] = []
        self._retriever: KeywordRetriever | None = None
        self._build_index()

    def _build_index(self) -> None:
        content = self.loader.load()
        self._chunks = self.splitter.split(content)
        self._retriever = KeywordRetriever(self._chunks)

    def search(self, question: str, top_k: int = 3) -> dict:
        if not self._retriever:
            return {
                "question": question,
                "source_path": str(self.source_path),
                "results": [],
            }

        results = self._retriever.retrieve(question, top_k=top_k)
        return {
            "question": question,
            "source_path": str(self.source_path),
            "results": results,
        }
