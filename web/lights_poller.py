"""Background poller for /light.html.

Runs as a long-living systemd service, probing every relay output
and every Tuya on/off switch on a fixed cadence and writing the
result into Redis. The web page reads from Redis on render, so a
permanently-dead device (Solar in with no PSU plugged, for example)
no longer blocks the response for the full 5 s tinytuya socket
timeout.

Intentionally self-contained: doesn't import the web app's config
module, which pulls pandas / influxdb / pythonjsonlogger — none of
which the host has installed (those live inside the smart-home
docker image). The relays + switches list comes straight from
conf/config.ini and conf/snapshot.json.

Redis schema written here, read by server_fastapi.py /light.html:
    light_state_<id> = pickle({"value": bool|None, "ts": <unix>, "name": "..."})
"""
import configparser
import http.client
import json
import logging
import os
import pickle
import sys
import time

import redis
import tinytuya

POLL_INTERVAL_S    = 30
SWITCH_PKEYS       = {"keyjup78v54myhan", "keyuh3jxk9wu8ruj"}
REDIS_KEY_PREFIX   = "light_state_"
TUYA_SOCK_TIMEOUT  = 5
TUYA_RETRY         = 2

HERE          = os.path.dirname(os.path.abspath(__file__))
CONFIG_INI    = os.path.join(HERE, "conf", "config.ini")
SNAPSHOT_JSON = os.path.join(HERE, "conf", "snapshot.json")

log = logging.getLogger("lights_poller")
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)


def _loadIni():
    cp = configparser.ConfigParser()
    cp.read(CONFIG_INI)
    return cp


def _httpRelay(ip, port):
    # Same shape conf.Lights.status() uses in the web app: GET on the
    # board returns a tiny JSON with {"v": 0|1}.
    conn = http.client.HTTPConnection(ip, timeout=3)
    conn.request("GET", "/?p=%s" % port)
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return json.loads(data).get("v")


def _probeRelay(name, ip, port):
    try:
        return _httpRelay(ip, port)
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


def _write(db, id_, name, value):
    payload = {"value": value, "ts": int(time.time()), "name": name}
    db.set(REDIS_KEY_PREFIX + id_, pickle.dumps(payload))


def _loadDevices():
    """Return (relays, tuya_switches). Both are lists of dicts with
    enough info to probe. Snapshot is re-read on every cycle so
    tuya_rediscover.py's IP updates propagate without a poller
    restart."""
    cp = _loadIni()
    # The relays live in [Lights].items as a Python-literal dict.
    relays_src = eval(cp["Lights"]["items"])
    relays = [
        {"id": id_, "name": item["name"], "ip": item["ip"], "port": item["port"]}
        for id_, item in relays_src.items()
    ]

    with open(SNAPSHOT_JSON) as f:
        snap = json.load(f)
    tuya_switches = [
        d for d in snap.get("devices", [])
        if d.get("productKey") in SWITCH_PKEYS
        and d.get("name") and d.get("ip")
    ]
    return relays, tuya_switches


def cycle(db):
    relays, tuya_switches = _loadDevices()
    for r in relays:
        _write(db, r["id"], r["name"], _probeRelay(r["name"], r["ip"], r["port"]))
    for d in tuya_switches:
        _write(db, d["id"], d["name"], _probeTuya(d))


def main():
    cp = _loadIni()
    db = redis.Redis(cp["Db"]["host"], int(cp["Db"]["port"]))
    log.info("lights_poller started, interval=%ds", POLL_INTERVAL_S)
    while True:
        t0 = time.time()
        try:
            cycle(db)
        except Exception as e:
            log.error("cycle failed: %s", e)
        time.sleep(max(1.0, POLL_INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
