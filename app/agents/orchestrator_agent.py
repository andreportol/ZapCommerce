from .base_agent import AgentExecutionError, create_base_agent, run_text
from .cardapio_agent import CardapioAgent
from .database_agent import DatabaseAgent
from .file_agent import FileAgent
from .instructions_agent import InstructionsAgent
from .llm_config import LLMConfigError
from .message_agent import MessageAgent


class OrchestratorAgent:
    """Coordena agentes e gera resposta final com LLM."""

    def __init__(self) -> None:
        self.message_agent = MessageAgent()
        self.instructions_agent = InstructionsAgent()
        self.cardapio_agent = CardapioAgent()
        self.database_agent = DatabaseAgent()
        self.file_agent = FileAgent()
        self._llm_agent = None
        try:
            self._llm_agent = create_base_agent(
                name="OrchestratorAgent",
                instructions=(
                    "Voce e um assistente de atendimento para WhatsApp de uma marmitaria.\n"
                    "Responda em portugues do Brasil, de forma objetiva, educada e natural.\n"
                    "Soe como atendente humano: linguagem simples, cordial e direta.\n"
                    "Evite tom robotico, frases engessadas e texto longo.\n"
                    "Quando fizer sentido, use no maximo 1 emoji discreto.\n"
                    "Nao invente dados.\n"
                    "Se faltarem informacoes para localizar pedido, informe isso e solicite numero do pedido.\n"
                    "Nao confirme pagamento automaticamente.\n"
                    "Nao altere status de pedido.\n"
                    "Nao diga que gravou dados no banco."
                ),
            )
        except LLMConfigError:
            self._llm_agent = None

    def handle_message(self, message: str, file_name: str = "", file_mimetype: str = "") -> dict:
        analysis = self.message_agent.analyze(message)
        instructions = self.instructions_agent.get_instructions()
        cardapio = self.cardapio_agent.get_cardapio()
        file_info = self.file_agent.parse_file_info(file_name, file_mimetype) if file_name else None

        if analysis.intent == "consultar pedido":
            db_result = self.database_agent.get_order_status(message)
        elif analysis.intent == "consultar pagamento":
            db_result = self.database_agent.get_payment_status(message)
        else:
            db_result = self.database_agent.general_lookup(message)

        context = self._build_context(
            message=message,
            intent=analysis.intent,
            instructions=instructions,
            cardapio=cardapio,
            db_result=db_result,
            file_info=file_info,
        )
        final_response = self._generate_final_response(context, analysis.intent, file_info is not None)
        return {
            "intent": analysis.intent,
            "database": db_result,
            "instructions": instructions,
            "cardapio_loaded": bool(cardapio),
            "file_info": file_info.__dict__ if file_info else None,
            "final_response": final_response,
        }

    def _build_context(
        self,
        message: str,
        intent: str,
        instructions: str,
        cardapio: str,
        db_result: dict,
        file_info,
    ) -> str:
        file_section = "nenhum"
        if file_info is not None:
            file_section = (
                f"nome={file_info.nome or 'nao informado'}, "
                f"extensao={file_info.extensao or 'nao informada'}, "
                f"mimetype={file_info.mimetype or 'nao informado'}"
            )

        return (
            f"Mensagem do usuario: {message}\n"
            f"Intencao detectada: {intent}\n"
            f"Resultado atual do banco: {db_result.get('message')}\n"
            f"Dados retornados do banco: {db_result.get('data')}\n"
            f"Arquivo recebido: {file_section}\n"
            f"Instrucoes de atendimento: {instructions}\n"
            f"Cardapio em arquivo texto:\n{cardapio or 'Nao ha cardapio carregado.'}\n"
            "Gere apenas a resposta final para o usuario em 1 a 4 frases curtas."
        )

    def _generate_final_response(self, context: str, intent: str, has_file: bool) -> str:
        if self._llm_agent is not None:
            try:
                response = run_text(self._llm_agent, context)
                if response:
                    return response
            except (AgentExecutionError, ValueError):
                pass
        return self._fallback_response(intent, has_file)

    def _fallback_response(self, intent: str, has_file: bool) -> str:
        if has_file or intent == "envio de comprovante":
            return (
                "Recebi seu arquivo e ele sera analisado pela equipe. "
                "Por seguranca, nao confirmamos pagamento automaticamente por aqui."
            )
        if intent == "consultar pedido":
            return (
                "Para consultar o status do seu pedido, preciso de mais dados. "
                "Por favor, me informe o numero do pedido."
            )
        if intent == "consultar pagamento":
            return (
                "Posso te ajudar com pagamento, mas preciso do numero do pedido "
                "para localizar as informacoes corretas."
            )
        if intent == "atendimento humano":
            return "Entendi. Vou encaminhar seu atendimento para uma pessoa da equipe."
        return "Posso te ajudar melhor se voce me contar mais detalhes do que precisa."


def run_orchestrator_test_cases() -> dict:
    orchestrator = OrchestratorAgent()
    status_case = orchestrator.handle_message("Olá, quero saber o status do meu pedido")
    file_case = orchestrator.handle_message(
        "Segue o comprovante de pagamento",
        file_name="comprovante_pix.jpg",
        file_mimetype="image/jpeg",
    )
    return {
        "status_case": status_case,
        "file_case": file_case,
    }
