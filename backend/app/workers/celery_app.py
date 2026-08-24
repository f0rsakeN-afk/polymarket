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
    task_reject_on_worker_lost=True,
    # DLQ: rejected / max-retries exceeded tasks go here for manual inspection
    task_queues={
        "celery": {
            "exchange": "celery",
            "routing_key": "celery",
            "arguments": {
                "x-dead-letter-exchange": "celery.dlx",
                "x-dead-letter-routing-key": "celery.dlx",
            },
        },
    },
    # Declare the DLX so RabbitMQ creates it automatically
    broker_transport_options={
        "master_name": "rabbitmq-master",
    },
    # Fallback: Redis broker doesn't support DLX natively — this is a no-op there,
    # but docker-compose / production should use RabbitMQ with the dlx arguments above.
    worker_send_task_events=True,
    task_send_sent_event=True,
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
        "task": "app.workers.tasks.check_markets_ready_to_resolve",
        "schedule": crontab(minute="*/5"),
    },
    "check-limit-order-execution": {
        "task": "app.workers.tasks.check_limit_order_execution",
        "schedule": 30.0,
    },
    "snapshot-price-history": {
        "task": "app.workers.tasks.snapshot_price_history",
        "schedule": 300.0,
    },
    "cleanup-expired-sessions": {
        "task": "app.workers.tasks.cleanup_expired_sessions",
        "schedule": crontab(hour=3, minute=0),  # 3am daily
    },
    "distribute-protocol-fees": {
        "task": "app.workers.tasks.distribute_protocol_fees",
        "schedule": crontab(hour=3, minute=30),  # 3:30am daily
    },
}
