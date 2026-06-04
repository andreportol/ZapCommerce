import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction

from .agents.orchestrator_agent import OrchestratorAgent
from .models import Cliente, ConfiguracaoMarmitaria, Conversa, Mensagem

logger = logging.getLogger(__name__)
orchestrator_agent = OrchestratorAgent()


def obter_configuracao_ativa():
    return ConfiguracaoMarmitaria.objects.filter(ativo=True).first()


def criar_ou_obter_cliente_por_telefone(telefone: str) -> Cliente:
    cliente, _ = Cliente.objects.get_or_create(telefone=telefone)
    return cliente


def obter_ou_criar_conversa_ativa(cliente: Cliente) -> Conversa:
    conversa = (
        Conversa.objects.filter(cliente=cliente)
        .exclude(status=Conversa.Status.FINALIZADA)
        .order_by('-atualizado_em')
        .first()
    )
    if conversa:
        return conversa
    return Conversa.objects.create(cliente=cliente, status=Conversa.Status.IA)


def salvar_mensagem(conversa: Conversa, origem: str, texto: str, whatsapp_message_id: str = '') -> Mensagem:
    msg = Mensagem.objects.create(
        conversa=conversa,
        origem=origem,
        texto=texto or '',
        whatsapp_message_id=whatsapp_message_id or '',
    )
    conversa.ultima_mensagem = (texto or '')[:1000]
    conversa.save(update_fields=['ultima_mensagem', 'atualizado_em'])
    return msg


def enviar_mensagem_whatsapp(telefone: str, texto: str) -> dict:
    url = (
        f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}',
        'Content-Type': 'application/json',
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': telefone,
        'type': 'text',
        'text': {'body': texto},
    }

    response = requests.post(url, json=payload, headers=headers, timeout=15)
    if response.status_code >= 400:
        logger.error(
            'Falha WhatsApp API status=%s body=%s',
            response.status_code,
            response.text,
        )
    response.raise_for_status()
    return response.json()


def obter_historico(conversa: Conversa, limite: int = 20):
    return list(conversa.mensagens.order_by('-criado_em')[:limite][::-1])


def _fallback_recovery_response() -> str:
    return (
        "Desculpe, tive uma dificuldade para continuar seu atendimento 😕\n"
        "Vamos recomeçar.\n\n"
        "Como posso ajudar?\n\n"
        "1 - Fazer pedido\n"
        "2 - Saber o cardápio\n"
        "3 - Mais informações\n"
        "4 - Falar com a atendente"
    )


def gerar_resposta_atendimento(
    texto: str,
    telefone: str = '',
    file_name: str = '',
    file_mimetype: str = '',
) -> str:
    try:
        result = orchestrator_agent.handle_message(
            texto,
            telefone=telefone,
            file_name=file_name,
            file_mimetype=file_mimetype,
        )
        resposta = (result.get('final_response') or '').strip()
        if resposta:
            return resposta
    except Exception as exc:
        logger.exception(
            'Falha ao gerar resposta com OrchestratorAgent telefone=%s texto=%r erro=%s acao=fallback',
            telefone,
            texto,
            exc,
        )
    logger.warning(
        'Resposta vazia no atendimento telefone=%s texto=%r acao=fallback_menu',
        telefone,
        texto,
    )
    return _fallback_recovery_response()


def deve_encaminhar_para_humano(texto: str, resposta: str) -> bool:
    texto_normalizado = (texto or '').strip().lower()
    resposta_normalizada = (resposta or '').strip().lower()

    if any(
        termo in texto_normalizado
        for termo in [
            'falar com atendente',
            'atendente',
            'humano',
            'pessoa',
            'falar com alguem',
        ]
    ):
        return True

    return (
        'encaminhar' in resposta_normalizada
        and (
            'atendente' in resposta_normalizada
            or 'pessoa da equipe' in resposta_normalizada
            or 'atendimento humano' in resposta_normalizada
        )
    )


def processar_mensagem_whatsapp(payload: dict) -> None:
    """
    Em producao, mover este processamento para Celery + Redis para evitar bloquear o webhook.
    """
    telefone = ''
    texto = ''
    resposta = ''
    conversa = None
    try:
        changes = payload.get('entry', [])[0].get('changes', [])
        if not changes:
            logger.info('Webhook sem changes (provavel status).')
            return

        value = changes[0].get('value', {})
        messages = value.get('messages', [])
        if not messages:
            logger.info('Webhook sem mensagens de texto (provavel evento de status).')
            return

        msg = messages[0]
        telefone = msg.get('from', '')
        message_id = msg.get('id', '')
        tipo = msg.get('type')
        file_name = ''
        file_mimetype = ''
        texto = ''

        if tipo == 'text':
            texto = msg.get('text', {}).get('body', '').strip()
        elif tipo in {'image', 'document'}:
            media = msg.get(tipo, {}) or {}
            file_name = media.get('filename') or media.get('id') or ''
            file_mimetype = media.get('mime_type') or ''
            texto = (media.get('caption') or '').strip() or 'Comprovante enviado'

        if not telefone:
            logger.warning('Mensagem recebida sem telefone.')
            return

        if not texto:
            logger.info('Mensagem nao textual recebida telefone=%s tipo=%s. Respondendo fallback de formato.', telefone, tipo)
            resposta = (
                'Recebi sua mensagem 😊\n\n'
                'No momento consigo te atender melhor por texto, imagem ou PDF. '
                'Se preferir, digite menu para recomeçar.'
            )
            enviar_mensagem_whatsapp(telefone=telefone, texto=resposta)
            return

        with transaction.atomic():
            cliente = criar_ou_obter_cliente_por_telefone(telefone)
            conversa = obter_ou_criar_conversa_ativa(cliente)
            salvar_mensagem(conversa, Mensagem.Origem.CLIENTE, texto, message_id)

            if conversa.status == Conversa.Status.HUMANO:
                logger.info('Conversa %s em modo humano, sem resposta automatica.', conversa.id)
                return

            resposta = gerar_resposta_atendimento(
                texto=texto,
                telefone=telefone,
                file_name=file_name,
                file_mimetype=file_mimetype,
            )
            if not resposta:
                return

            salvar_mensagem(conversa, Mensagem.Origem.IA, resposta)
            if deve_encaminhar_para_humano(texto=texto, resposta=resposta):
                conversa.status = Conversa.Status.HUMANO
                conversa.save(update_fields=['status', 'atualizado_em'])
                salvar_mensagem(
                    conversa=conversa,
                    origem=Mensagem.Origem.SISTEMA,
                    texto='Conversa encaminhada para atendimento humano.',
                )

        try:
            enviar_mensagem_whatsapp(telefone=telefone, texto=resposta)
        except Exception as exc:
            logger.exception('Erro ao enviar mensagem WhatsApp: %s', exc)
            try:
                salvar_mensagem(
                    conversa=conversa,
                    origem=Mensagem.Origem.SISTEMA,
                    texto=f'Falha no envio WhatsApp: {exc}',
                )
            except Exception:
                logger.exception('Falha ao salvar mensagem de sistema sobre erro de envio.')

    except Exception as exc:
        logger.exception(
            'Erro ao processar webhook telefone=%s texto=%r erro=%s acao=fallback_envio',
            telefone,
            texto,
            exc,
        )
        if not telefone:
            return
        fallback_text = _fallback_recovery_response()
        try:
            enviar_mensagem_whatsapp(telefone=telefone, texto=fallback_text)
        except Exception:
            logger.exception(
                'Falha ao enviar fallback do webhook telefone=%s texto=%r',
                telefone,
                texto,
            )
        try:
            if conversa is not None:
                salvar_mensagem(conversa, Mensagem.Origem.SISTEMA, fallback_text)
        except Exception:
            logger.exception(
                'Falha ao registrar fallback do webhook telefone=%s texto=%r',
                telefone,
                texto,
            )


def parse_decimal(valor):
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))
