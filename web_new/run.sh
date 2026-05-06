#!/bin/bash
set -m

python -m tornado.autoreload /root/project/server.py &

if python -c "import checker" 2>/dev/null; then
    python /root/project/checkerd.py
fi

fg %1
