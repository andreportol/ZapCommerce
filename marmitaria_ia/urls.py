from django.contrib import admin
from django.urls import path

from app.views import health_view, home_view, whatsapp_webhook_view

urlpatterns = [
    path('', home_view, name='home'),
    path('admin/', admin.site.urls),
    path('api/whatsapp/webhook/', whatsapp_webhook_view, name='whatsapp_webhook'),
    path('health/', health_view, name='health'),
]
