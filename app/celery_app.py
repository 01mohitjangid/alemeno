"""Celery application instance.

Run the worker with:
    celery -A app.celery_app.celery_app worker --loglevel=info
"""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "alemeno",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.processing"],  # modules to import on worker start
)

celery_app.conf.update(
    task_track_started=True,          # emit a STARTED state -> maps to "processing"
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=60 * 60 * 24,      # keep task results for 24h
    timezone="UTC",
    enable_utc=True,
    worker_max_tasks_per_child=100,   # recycle workers to bound memory growth
    broker_connection_retry_on_startup=True,  # retry broker on boot (Celery 5.x)
)
