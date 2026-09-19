# Gunicorn config for 50k+ concurrent WebSocket users
# Uses uvicorn workers for async FastAPI
import multiprocessing

bind = "0.0.0.0:8000"
workers = 8  # one per core; each runs its own event loop + Redis listener
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = 120
timeout = 120  # must be >= keepalive for WebSocket long-lived conns (M4 fix)
graceful_timeout = 30
max_requests = 10000
max_requests_jitter = 1000

# Preload app so DB pools are initialized before forking
# Disabled: async engines / redis pools must be created per-worker after fork.
preload_app = False

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Each worker gets its own Redis pub/sub consumer (handled in app startup)
