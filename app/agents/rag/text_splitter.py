import re


class TextSplitter:
    """Divide texto em trechos menores para recuperação simples."""

    def __init__(self, min_chunk_len: int = 40) -> None:
        self.min_chunk_len = min_chunk_len

    def split(self, text: str) -> list[str]:
        if not text:
            return []

        blocks = re.split(r"\n\s*\n+", text.strip())
        chunks: list[str] = []
        for block in blocks:
            cleaned = " ".join(block.split())
            if len(cleaned) >= self.min_chunk_len:
                chunks.append(cleaned)
        return chunks
