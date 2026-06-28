"""Background poller for /light.html.

Runs as a long-living systemd service, probing every relay output
and every Tuya on/off switch on a fixed cadence and writing the
result into Redis. The web page reads from Redis on render, so a
permanently-dead device (Solar in with no PSU plugged, for example)
no longer blocks the response for the full 5 s tinytuya socket
timeout — the page renders instantly and we just miss one cycle
of fresh state for that one box.

State payload pickled at `light_state_<id>`:
    {"value": bool|None, "ts": <unix-ts>, "name": "..."}

Where value=None means "we tried this cycle and the device didn't
answer", and ts lets the renderer decide between fresh / stale.
"""
import json
import logging
import os
import pickle
import sys
import time

# Make `from config import conf` resolvable when launched from systemd
# with WorkingDirectory=/.../web.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tinytuya
from config import conf, sendReq

POLL_INTERVAL_S    = 30
SWITCH_PKEYS       = {"keyjup78v54myhan", "keyuh3jxk9wu8ruj"}
REDIS_KEY_PREFIX   = "light_state_"
TUYA_SOCK_TIMEOUT  = 5
TUYA_RETRY         = 2

log = logging.getLogger("lights_poller")
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)


def _write(db, id_, name, value):
    payload = {"value": value, "ts": int(time.time()), "name": name}
    db.set(REDIS_KEY_PREFIX + id_, pickle.dumps(payload))


def _probeRelay(name, ip, port):
    try:
        raw = sendReq(ip, "/?p=%s" % port)
        return json.loads(raw).get("v")
    except Exception as e:
        log.warning("relay %s probe failed: %s", name, e)
        return None


def _probeTuya(dev):
    try:
        d = tinytuya.OutletDevice(
            dev_id=dev["id"], address=dev["ip"],
            local_key=dev["key"], version=dev["ver"],
        )
        d.set_socketTimeout(TUYA_SOCK_TIMEOUT)
        d.set_socketRetryLimit(TUYA_RETRY)
        status = d.status()
        return status.get("dps", {}).get("1")
    except Exception as e:
        log.warning("tuya %s probe failed: %s", dev.get("name", "?"), e)
        return None


def cycle(db):
    for id_, item in conf.Lights.items.items():
        v = _probeRelay(item.get("name", id_), item["ip"], item["port"])
        _write(db, id_, item.get("name", id_), v)

    for _id, dev in conf.Tuya.devices.items():
        if dev.get("productKey") not in SWITCH_PKEYS:
            continue
        if not dev.get("name") or not dev.get("ip"):
            continue
        v = _probeTuya(dev)
        _write(db, dev["id"], dev["name"], v)


def main():
    db = conf.db.conn
    log.info("lights_poller started, interval=%ds", POLL_INTERVAL_S)
    while True:
        t0 = time.time()
        try:
            cycle(db)
        except Exception as e:
            log.error("cycle failed: %s", e)
        # Always sleep at least 1 s so a stream of consecutive errors
        # can't pin the CPU.
        time.sleep(max(1.0, POLL_INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
