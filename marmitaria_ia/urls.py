from django.contrib import admin
from django.urls import path

from app.views import (
    DashboardView,
    PublicLoginView,
    PublicLogoutView,
    dashboard_update_order_status_view,
    health_view,
    home_view,
    whatsapp_webhook_view,
)

urlpatterns = [
    path('', home_view, name='home'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/pedidos/<int:pedido_id>/status/', dashboard_update_order_status_view, name='dashboard_update_order_status'),
    path('login/', PublicLoginView.as_view(), name='login'),
    path('logout/', PublicLogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('api/whatsapp/webhook/', whatsapp_webhook_view, name='whatsapp_webhook'),
    path('health/', health_view, name='health'),
]
