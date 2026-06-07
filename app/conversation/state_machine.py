from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .states import AwaitingResponse
from .transitions import TRANSITION_RULES


@dataclass(frozen=True)
class TransitionExplanation:
    current_awaiting_response: str
    user_message: str
    expected_next_awaiting_response: str
    matched: bool
    description: str


class ConversationStateMachine:
    """State machine auxiliar para validar transições conhecidas em testes."""

    NOT_MAPPED = AwaitingResponse.NOT_MAPPED.value

    def get_expected_next_awaiting_response(self, current_awaiting_response: str, user_message: str) -> str:
        normalized = self._normalize(user_message)
        current = self._normalize_state_key(current_awaiting_response)
        for rule in TRANSITION_RULES:
            if self._normalize_state_key(rule.current) != current:
                continue
            if rule.matcher(normalized):
                return rule.next
        return self.NOT_MAPPED

    def is_transition_allowed(self, current_awaiting_response: str, user_message: str, next_awaiting_response: str) -> bool:
        expected = self.get_expected_next_awaiting_response(current_awaiting_response, user_message)
        if expected == self.NOT_MAPPED:
            return False
        return self._normalize_state_key(expected) == self._normalize_state_key(next_awaiting_response)

    def explain_transition(self, current_awaiting_response: str, user_message: str) -> TransitionExplanation:
        normalized = self._normalize(user_message)
        current = self._normalize_state_key(current_awaiting_response)
        for rule in TRANSITION_RULES:
            if self._normalize_state_key(rule.current) != current:
                continue
            if rule.matcher(normalized):
                return TransitionExplanation(
                    current_awaiting_response=current_awaiting_response,
                    user_message=user_message,
                    expected_next_awaiting_response=rule.next,
                    matched=True,
                    description=rule.description,
                )
        return TransitionExplanation(
            current_awaiting_response=current_awaiting_response,
            user_message=user_message,
            expected_next_awaiting_response=self.NOT_MAPPED,
            matched=False,
            description="Transição ainda não mapeada pela state machine auxiliar.",
        )

    def _normalize(self, text: str) -> str:
        raw = (text or "").strip().lower()
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        raw = re.sub(r"[^a-z0-9\s]", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()

    def _normalize_state_key(self, text: str) -> str:
        return (text or "").strip().lower()
