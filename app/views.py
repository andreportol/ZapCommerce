import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .services import processar_mensagem_whatsapp

logger = logging.getLogger(__name__)


@require_GET
def home_view(_request: HttpRequest):
    return JsonResponse(
        {
            'status': 'ok',
            'projeto': 'marmitaria_ia',
            'rotas': ['/admin/', '/health/', '/api/whatsapp/webhook/'],
        }
    )


@require_GET
def health_view(_request: HttpRequest):
    return JsonResponse({'status': 'ok'})


@csrf_exempt
def whatsapp_webhook_view(request: HttpRequest):
    if request.method == 'GET':
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')

        if mode == 'subscribe' and token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge or '', status=200)
        return JsonResponse({'error': 'invalid verify token'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    try:
        processar_mensagem_whatsapp(payload)
    except Exception as exc:
        logger.exception('Erro interno no webhook: %s', exc)

    return JsonResponse({'status': 'ok'})
