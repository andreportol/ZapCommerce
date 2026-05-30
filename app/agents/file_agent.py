from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileInfo:
    nome: str
    extensao: str
    mimetype: str


class FileAgent:
    """
    Estrutura inicial para dados de arquivo.
    Nesta etapa nao valida comprovante.
    """

    def parse_file_info(self, nome: str, mimetype: str | None = None) -> FileInfo:
        file_name = (nome or "").strip()
        suffix = Path(file_name).suffix.lower() if file_name else ""
        return FileInfo(
            nome=file_name,
            extensao=suffix,
            mimetype=(mimetype or "").strip(),
        )
