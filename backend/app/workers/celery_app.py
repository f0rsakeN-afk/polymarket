from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "polymarket",
    broker=settings.celery_broker_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=4,  # cap to avoid overwhelming the DB; separate processes = separate connection pools
)

celery_app.conf.beat_schedule = {
    "expire-stale-orders": {
        "task": "app.workers.tasks.expire_stale_orders",
        "schedule": 30.0,
    },
    "sync-amm-prices": {
        "task": "app.workers.tasks.sync_amm_prices",
        "schedule": 60.0,
    },
    "check-market-resolution": {
        "task": "app.workers.tasks.check_market_resolution",
        "schedule": crontab(minute="*/5"),
    },
}
