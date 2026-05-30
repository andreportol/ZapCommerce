from pathlib import Path


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
            return DEFAULT_INSTRUCTIONS

        content = self.instructions_path.read_text(encoding="utf-8").strip()
        return content or DEFAULT_INSTRUCTIONS
