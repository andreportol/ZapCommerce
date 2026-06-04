from decimal import Decimal
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView

from .forms import EmailOrUsernameAuthenticationForm
from .models import Pedido
from .services import processar_mensagem_whatsapp

logger = logging.getLogger(__name__)


def _format_currency(value: Decimal) -> str:
    return f'R$ {value:.2f}'.replace('.', ',')


def _payment_label(forma_pagamento: str) -> str:
    if not forma_pagamento:
        return 'A definir'
    return dict(Pedido.FormaPagamento.choices).get(forma_pagamento, forma_pagamento)


def _delivery_label(pedido: Pedido) -> str:
    if pedido.endereco_entrega:
        return 'Entrega'
    if pedido.status in {
        Pedido.Status.AGUARDANDO_PAGAMENTO,
        Pedido.Status.PAGO,
        Pedido.Status.EM_PREPARO,
        Pedido.Status.SAIU_PARA_ENTREGA,
        Pedido.Status.ENTREGUE,
    }:
        return 'Retirada no local'
    return 'A definir'


def _dashboard_redirect(notice: str = ''):
    url = reverse('dashboard')
    if notice:
        return redirect(f'{url}?notice={notice}')
    return redirect(url)


def _dashboard_order_actions(pedido: Pedido) -> list[dict]:
    actions: list[dict] = []
    if pedido.status == Pedido.Status.AGUARDANDO_PAGAMENTO:
        actions.append(
            {
                'value': 'confirm_payment',
                'label': 'Confirmar pagamento',
                'tone': 'action-primary',
            }
        )
    elif pedido.status in {Pedido.Status.AGUARDANDO_CONFIRMACAO, Pedido.Status.PAGO}:
        actions.append(
            {
                'value': 'start_preparing',
                'label': 'Enviar para preparo',
                'tone': 'action-secondary',
            }
        )

    if pedido.status in {Pedido.Status.EM_PREPARO, Pedido.Status.SAIU_PARA_ENTREGA}:
        actions.append(
            {
                'value': 'finish_order',
                'label': 'Finalizar pedido',
                'tone': 'action-success',
            }
        )
    return actions


@require_GET
def home_view(request: HttpRequest):
    return render(request, 'landing/home.html')


@require_GET
def health_view(_request: HttpRequest):
    return JsonResponse({'status': 'ok'})


class PublicLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = EmailOrUsernameAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or '/dashboard/'


class PublicLogoutView(LogoutView):
    http_method_names = ['get', 'post', 'options']
    next_page = reverse_lazy('home')


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/home.html'
    login_url = reverse_lazy('login')

    STATUS_META = [
        (
            Pedido.Status.RASCUNHO,
            'Rascunho',
            'Pedido iniciado e ainda em montagem',
            'status-neutral',
        ),
        (
            Pedido.Status.AGUARDANDO_CONFIRMACAO,
            'Aguardando confirmação',
            'Pedido pronto para validação final',
            'status-warning',
        ),
        (
            Pedido.Status.AGUARDANDO_PAGAMENTO,
            'Aguardando pagamento',
            'Pedidos aguardando pagamento ou comprovante',
            'status-info',
        ),
        (
            Pedido.Status.PAGO,
            'Pago',
            'Pedidos pagos aguardando preparo',
            'status-success',
        ),
        (
            Pedido.Status.EM_PREPARO,
            'Em preparo',
            'Pedidos sendo produzidos pela cozinha',
            'status-prep',
        ),
        (
            Pedido.Status.SAIU_PARA_ENTREGA,
            'Saiu para entrega',
            'Pedidos já despachados para o cliente',
            'status-route',
        ),
        (
            Pedido.Status.ENTREGUE,
            'Entregue',
            'Pedidos concluídos com sucesso',
            'status-done',
        ),
        (
            Pedido.Status.CANCELADO,
            'Cancelado',
            'Pedidos cancelados no dia',
            'status-cancelled',
        ),
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        pedidos_hoje = (
            Pedido.objects.filter(criado_em__date=today)
            .select_related('cliente')
            .order_by('-criado_em')
        )
        faturamento = (
            pedidos_hoje.exclude(status=Pedido.Status.CANCELADO)
            .aggregate(total=Sum('total'))
            .get('total')
            or Decimal('0.00')
        )
        status_labels = {
            status_value: label
            for status_value, label, _description, _tone in self.STATUS_META
        }
        status_tones = {
            status_value: tone
            for status_value, _label, _description, tone in self.STATUS_META
        }
        status_counts = {
            status_value: pedidos_hoje.filter(status=status_value).count()
            for status_value, _label, _description, _tone in self.STATUS_META
        }
        recent_orders = []
        for pedido in pedidos_hoje[:10]:
            cliente_nome = (pedido.cliente.nome or '').strip() or pedido.cliente.telefone
            recent_orders.append(
                {
                    'id': pedido.id,
                    'client_name': cliente_nome,
                    'created_at': timezone.localtime(pedido.criado_em).strftime('%H:%M'),
                    'fulfillment': _delivery_label(pedido),
                    'payment': _payment_label(pedido.forma_pagamento),
                    'status_label': status_labels.get(pedido.status, pedido.get_status_display()),
                    'status_tone': status_tones.get(pedido.status, 'status-neutral'),
                    'total': _format_currency(pedido.total or Decimal('0.00')),
                    'actions': _dashboard_order_actions(pedido),
                }
            )

        context.update(
            {
                'dashboard_cards': [
                    {
                        'label': 'Pedidos de hoje',
                        'value': pedidos_hoje.count(),
                        'description': 'Pedidos registrados hoje',
                    },
                    {
                        'label': 'Pedidos pendentes',
                        'value': pedidos_hoje.filter(
                            status__in=[
                                Pedido.Status.RASCUNHO,
                                Pedido.Status.AGUARDANDO_CONFIRMACAO,
                                Pedido.Status.AGUARDANDO_PAGAMENTO,
                                Pedido.Status.PAGO,
                            ]
                        ).count(),
                        'description': 'Aguardando confirmação, pagamento ou início de preparo',
                    },
                    {
                        'label': 'Pedidos em preparo',
                        'value': pedidos_hoje.filter(status=Pedido.Status.EM_PREPARO).count(),
                        'description': 'Pedidos atualmente em produção',
                    },
                    {
                        'label': 'Pedidos finalizados',
                        'value': pedidos_hoje.filter(status=Pedido.Status.ENTREGUE).count(),
                        'description': 'Pedidos entregues hoje',
                    },
                    {
                        'label': 'Faturamento do dia',
                        'value': _format_currency(faturamento),
                        'description': 'Total acumulado dos pedidos do dia',
                    },
                ],
                'status_markers': [
                    {
                        'value': status_counts[status_value],
                        'label': label,
                        'description': description,
                        'tone': tone,
                    }
                    for status_value, label, description, tone in self.STATUS_META
                ],
                'recent_orders': recent_orders,
                'dashboard_notice': (self.request.GET.get('notice') or '').strip(),
                'today_label': today.strftime('%d/%m/%Y'),
            }
        )
        return context


@login_required(login_url=reverse_lazy('login'))
@require_POST
def dashboard_update_order_status_view(request: HttpRequest, pedido_id: int):
    pedido = get_object_or_404(Pedido, pk=pedido_id)
    action = (request.POST.get('action') or '').strip()

    if action == 'confirm_payment':
        if pedido.status != Pedido.Status.AGUARDANDO_PAGAMENTO:
            return _dashboard_redirect('status_invalido')
        pedido.status = Pedido.Status.EM_PREPARO
        pedido.save(update_fields=['status', 'atualizado_em'])
        return _dashboard_redirect('pagamento_confirmado')

    if action == 'start_preparing':
        if pedido.status not in {Pedido.Status.AGUARDANDO_CONFIRMACAO, Pedido.Status.PAGO}:
            return _dashboard_redirect('status_invalido')
        pedido.status = Pedido.Status.EM_PREPARO
        pedido.save(update_fields=['status', 'atualizado_em'])
        return _dashboard_redirect('pedido_em_preparo')

    if action == 'finish_order':
        if pedido.status not in {Pedido.Status.EM_PREPARO, Pedido.Status.SAIU_PARA_ENTREGA}:
            return _dashboard_redirect('status_invalido')
        pedido.status = Pedido.Status.ENTREGUE
        pedido.save(update_fields=['status', 'atualizado_em'])
        return _dashboard_redirect('pedido_finalizado')

    return _dashboard_redirect('acao_invalida')


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
