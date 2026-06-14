#!/bin/bash
set -m

# Web — gunicorn + uvicorn workers, 4 workers so a slow tinytuya / Influx
# call only stalls one of them, the others keep serving.
gunicorn \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --chdir /root/project \
    --access-logfile - \
    --error-logfile - \
    --timeout 60 \
    --graceful-timeout 10 \
    server_fastapi:app &

# Background checker daemon (heating logic, solar boost, etc.)
python3 /root/project/checkerd.py

fg %1
