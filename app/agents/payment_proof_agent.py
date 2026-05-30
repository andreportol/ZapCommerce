import re
import unicodedata
from dataclasses import asdict, dataclass


@dataclass
class PaymentProofAnalysis:
    received: bool
    can_confirm_payment: bool
    needs_manual_review: bool
    reason: str
    file_name: str = ""
    mimetype: str = ""


class PaymentProofAgent:
    """
    Analisa sinais basicos de envio de comprovante.

    Confirmacao real de pagamento depende de integracao bancaria/PIX.
    Este agente apenas identifica que um comprovante foi recebido para conferencia.
    """

    RECEIPT_TERMS = {
        "comprovante",
        "paguei",
        "pagamento feito",
        "pix feito",
        "pix enviado",
        "segue",
        "enviei",
        "enviado",
        "anexo",
    }

    RECEIPT_MIMETYPES = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
    }

    def analyze(self, text: str = "", file_name: str = "", mimetype: str = "") -> dict:
        normalized = self._normalize(text)
        clean_mimetype = (mimetype or "").strip().lower()
        clean_file_name = (file_name or "").strip()

        has_file = bool(clean_file_name or clean_mimetype)
        supported_file = bool(clean_mimetype in self.RECEIPT_MIMETYPES)
        has_receipt_text = any(term in normalized for term in self.RECEIPT_TERMS)

        if has_file and (supported_file or not clean_mimetype):
            return asdict(
                PaymentProofAnalysis(
                    received=True,
                    can_confirm_payment=False,
                    needs_manual_review=True,
                    reason="Arquivo de comprovante recebido para conferencia.",
                    file_name=clean_file_name,
                    mimetype=clean_mimetype,
                )
            )

        if has_receipt_text:
            return asdict(
                PaymentProofAnalysis(
                    received=True,
                    can_confirm_payment=False,
                    needs_manual_review=True,
                    reason="Mensagem indica envio ou realizacao de pagamento.",
                    file_name=clean_file_name,
                    mimetype=clean_mimetype,
                )
            )

        return asdict(
            PaymentProofAnalysis(
                received=False,
                can_confirm_payment=False,
                needs_manual_review=False,
                reason="Nenhum comprovante identificado na mensagem.",
                file_name=clean_file_name,
                mimetype=clean_mimetype,
            )
        )

    def _normalize(self, text: str) -> str:
        raw = (text or "").strip().lower()
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        raw = re.sub(r"[^a-z0-9\s]", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()
