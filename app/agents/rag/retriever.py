import re
import unicodedata
from collections import Counter


def _normalize(text: str) -> str:
    lowered = text.lower()
    no_accents = "".join(
        ch for ch in unicodedata.normalize("NFD", lowered) if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"\s+", " ", no_accents).strip()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize(text))


def _extract_numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\b\d+\b", _normalize(text))]


class KeywordRetriever:
    """Busca simples de trechos com base em similaridade textual/palavras-chave."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self._chunk_tokens = [_tokenize(chunk) for chunk in chunks]

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        query_tokens = _tokenize(query)
        query_numbers = _extract_numbers(query)
        if not query_tokens:
            return []

        query_counter = Counter(query_tokens)
        scored: list[tuple[int, int, str]] = []

        for idx, tokens in enumerate(self._chunk_tokens):
            token_counter = Counter(tokens)
            overlap = sum(min(query_counter[t], token_counter[t]) for t in query_counter)
            score = overlap
            chunk_text_norm = _normalize(self.chunks[idx])

            # Regra de reforco para perguntas com quantidade > 5 pessoas.
            if any(n > 5 for n in query_numbers):
                if "acima de 5 pessoas" in chunk_text_norm or "mais de 5 pessoas" in chunk_text_norm:
                    score += 5

            if score > 0:
                scored.append((score, idx, self.chunks[idx]))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[: max(1, top_k)]
        return [{"score": score, "chunk_index": idx, "text": text} for score, idx, text in top]
