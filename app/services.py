import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction

from .agents.marmitaria_agent import responder_com_agente
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
        logger.exception('Falha ao gerar resposta com OrchestratorAgent: %s', exc)
    return ''


def processar_mensagem_whatsapp(payload: dict) -> None:
    """
    Em producao, mover este processamento para Celery + Redis para evitar bloquear o webhook.
    """
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
            logger.info('Mensagem nao textual recebida. Estrutura preparada para futura extensao.')
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
                resposta = responder_com_agente(cliente=cliente, conversa=conversa, texto=texto)
            if not resposta:
                return

            salvar_mensagem(conversa, Mensagem.Origem.IA, resposta)

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
        logger.exception('Erro ao processar webhook: %s', exc)


def parse_decimal(valor):
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))
