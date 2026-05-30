from celery import shared_task


@shared_task(name='app.debug_celery_task')
def debug_celery_task(message: str) -> str:
    return f'Celery task executada com sucesso. Mensagem recebida: {message}'
