#!/bin/bash
# Dev-only helper — kill whatever daemon is running and start a fresh
# one under nohup so it survives our ssh session. Production uses the
# systemd unit; this is for tuning the pack subset without touching
# systemctl.
#
#   ./restart_daemon.sh                             # all packs
#   BMS_PACKS=battery-3,battery-5 ./restart_daemon.sh
#
# Log lands in /tmp/bms_run.log.
pkill -9 -f bms_daemon 2>/dev/null
sleep 2
sudo systemctl restart bluetooth
sleep 4
rm -f /tmp/bms_run.log
nohup env BMS_PACKS="${BMS_PACKS:-}" \
    /home/pi/bms/bin/python /home/pi/bms_daemon.py \
    > /tmp/bms_run.log 2>&1 &
echo "started pid=$!"
