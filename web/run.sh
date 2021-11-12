#/bin/bash
set -m

python -m tornado.autoreload /root/project/server.py &
python /root/project/checkerd.py
fg %1





