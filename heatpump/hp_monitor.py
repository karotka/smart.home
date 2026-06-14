import os
import sys
import tinytuya
import json
import pprint
import time
import logging
import pandas as pd

from influxdb import DataFrameClient
from logging.handlers import RotatingFileHandler





mapping = {
        "1" : "on",
        "2" : "workMode",
        "5" : "mode",
        "6" : "temperatureUnit",
        "101" : "waterInletTemperature",
        "102" : "waterOutletTemperature",
        "103" : "ambientTemperature",
        "104" : "exhaustGasTemperature",
        "105" : "returnGasTemperature",
        "106" : "evaporatorCoilTemperature",
        "107" : "coolingCoilTemperature",
        "108" : "waterTankTemperature",
        "109" : "openingOfMainEEV",
        "111" : "openingOfAssistantEEV",
        "112" : "compresorCurrent",
        "113" : "heatSinkTemperature",
        "114" : "DCBusVoltage",
        "115" : "compresorFrequency",
        "116" : "windSpeedFan1",
        "117" : "windSpeedFan2"
        }

mapping1 = {
        "101" : "waterInletTemperature",
        "102" : "waterOutletTemperature",
        "103" : "ambientTemperature",
        "104" : "exhaustGasTemperature",
        "105" : "returnGasTemperature",
        "106" : "evaporatorCoilTemperature",
        "107" : "coolingCoilTemperature",
        "108" : "waterTankTemperature",
        "109" : "openingOfMainEEV",
        "111" : "openingOfAssistantEEV",
        "112" : "compresorCurrent",
        "113" : "heatSinkTemperature",
        "114" : "DCBusVoltage",
        "115" : "compresorFrequency",
        "116" : "windSpeedFan1"
        }

def div1000(v): return v/1000
def div10(v): return v/10

mapping2 = {
        "18"  : "current", "18_f" : div1000,
        "19"  : "power",   "19_f" : div10,
        "20"  : "voltage", "20_f" : div10,
        }
pidfile = "/tmp/hp.pid"

def createPid():

    pid = str(os.getpid())

    if os.path.isfile(pidfile):
        print ("%s already exists, exiting" % pidfile)
        sys.exit()

    f = open(pidfile, 'w')
    f.write(pid)

createPid()

def createLog():
    """
    Creates a rotating log
    """
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log/hp_log")
    handler = RotatingFileHandler(log_path, backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s hp [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


def getClient():
    while True:
        try:
            return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'hp')
        except:
            logging.error(e, exc_info = True)
            time.sleep(3)


def writeDb(data):
    dt = pd.to_datetime('today').now(tz = 'Europe/Prague')
    df = pd.DataFrame(data, index=[0])

    df["time"] = dt
    df.set_index(['time'], inplace = True)

    client = getClient()
    client.write_points(df, 'hp', protocol = 'line')
    logging.info("Send data ok time: %s" % (dt))


def remapAllKeys(dps):
    dps1 = dict()
    for k, v in dps.items():
        dps1[mapping.get(k, k)] = v
    return dps1


def remapKeys(dps):
    dps1 = dict()
    for k, v in dps.items():
        if mapping1.get(k, None):
            dps1[mapping1[k]] = v
    return dps1


def remapKeys1(dps):
    dps1 = dict()
    for k, v in dps.items():
        if mapping2.get(k, None):
            fn = mapping2.get(k + "_f")
            dps1[mapping2[k]] = fn(v)
    return dps1

HP_ID = "bf06f140ee20807fdaalyq"
TC_ID = "bf2f6c60f5d1b15d9c6urw"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_PATH = os.path.join(HERE, "snapshot.json")

# Local keys live in snapshot.json (same file the web app reads), so we
# keep one source of truth. IPs in the snapshot are also the last known
# good ones — we refresh them from a tinytuya UDP scan whenever a device
# stops answering, because DHCP can hand it a new lease at any time and
# the TC switch firmware has no static-IP option.
with open(SNAPSHOT_PATH) as _f:
    _snap_raw = json.load(_f)
_snap = {x["id"]: x for x in _snap_raw["devices"]}

DEVICES = {
    HP_ID: {"label": "hp",        "ver": "3.3", "remap": (lambda dps: remapKeys(dps))},
    TC_ID: {"label": "hp-switch", "ver": "3.4", "remap": (lambda dps: remapKeys1(dps))},
}


def _persistSnapshot():
    """Write the in-memory _snap_raw back to disk so the next process
    start gets the freshly-discovered IPs without paying for a scan."""
    try:
        with open(SNAPSHOT_PATH, "w") as f:
            json.dump(_snap_raw, f, indent=4, ensure_ascii=False)
    except Exception:
        logging.exception("snapshot persist failed")


def _rediscover(reason):
    """UDP-scan the LAN, update _snap[*]['ip'] for HP_ID/TC_ID if found,
    persist, and return the set of IDs whose IP actually changed."""
    logging.info("tuya rediscover: %s", reason)
    try:
        found = tinytuya.deviceScan(verbose=False, maxretry=15) or {}
    except Exception as e:
        logging.warning("tuya scan failed: %s", e)
        return set()
    changed = set()
    by_id = {meta.get("gwId") or meta.get("id"): (ip, meta)
             for ip, meta in found.items()}
    for did in (HP_ID, TC_ID):
        meta = by_id.get(did)
        if not meta:
            logging.warning("tuya scan: %s not on LAN", did[:10])
            continue
        new_ip = meta[0]
        if _snap[did].get("ip") != new_ip:
            logging.info("tuya %s ip %s -> %s",
                         did[:10], _snap[did].get("ip"), new_ip)
            _snap[did]["ip"] = new_ip
            changed.add(did)
    if changed:
        _persistSnapshot()
    return changed


def _buildDevice(did):
    meta = _snap[did]
    dev = tinytuya.OutletDevice(dev_id=did, address=meta["ip"],
                                local_key=meta["key"],
                                version=DEVICES[did]["ver"])
    dev.set_socketTimeout(8)
    dev.set_socketRetryLimit(1)
    return dev


def _readDps(device, label):
    """One plain status() call. Returns None on error or when the device
    replies without a `dps` payload (offline / wrong key / Tuya error)."""
    try:
        data = device.status()
    except Exception as e:
        logging.warning("tuya %s status failed: %s", label, e)
        return None
    dps = (data or {}).get("dps")
    if dps is None:
        logging.warning("tuya %s returned no dps: %s",
                        label, str(data)[:200])
        return None
    return dps


devices = {did: _buildDevice(did) for did in DEVICES}
fail_streak = {did: 0 for did in DEVICES}
# After this many consecutive empty reads on a device, assume DHCP moved
# it and trigger a fresh scan. 12 ticks * 5 s = 1 minute — slow enough
# that a brief router hiccup doesn't trip it, fast enough to recover in
# minutes rather than days.
REDISCOVER_AFTER = 12

try:
    while True:
        dataDict = {}

        for did in DEVICES:
            dps = _readDps(devices[did], DEVICES[did]["label"])
            if dps is not None:
                dataDict.update(DEVICES[did]["remap"](dps))
                fail_streak[did] = 0
            else:
                fail_streak[did] += 1

        stale = [did for did, n in fail_streak.items() if n >= REDISCOVER_AFTER]
        if stale:
            changed = _rediscover("stale=%s" % [d[:10] for d in stale])
            for did in changed:
                devices[did] = _buildDevice(did)
                fail_streak[did] = 0
            # Reset the counter even for stale devices we couldn't find,
            # so we wait another full minute before scanning again.
            for did in stale:
                if did not in changed:
                    fail_streak[did] = 0

        if dataDict:
            try:
                writeDb(dataDict)
            except Exception:
                logging.exception("writeDb failed")
        # else: both devices offline — skip the InfluxDB write entirely,
        # don't pollute the series with empty rows.

        time.sleep(5)

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)

