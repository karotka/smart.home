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

# Local keys live in snapshot.json (same file the web app reads), so we
# keep one source of truth. IPs are kept here because DHCP rarely shuffles
# them and we don't want a UDP discovery loop in the hot path.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "snapshot.json")) as _f:
    _snap = {x["id"]: x for x in json.load(_f)["devices"]}

d = tinytuya.OutletDevice(dev_id=HP_ID, address="192.168.0.192",
                          local_key=_snap[HP_ID]["key"], version="3.3")
d.set_socketTimeout(8)
d.set_socketRetryLimit(1)

d1 = tinytuya.OutletDevice(dev_id=TC_ID, address="192.168.0.18",
                           local_key=_snap[TC_ID]["key"], version="3.4")
d1.set_socketTimeout(8)
d1.set_socketRetryLimit(1)


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


try:

    while True:
        dataDict = {}

        dps = _readDps(d, "hp")
        if dps is not None:
            dataDict.update(remapKeys(dps))

        dps1 = _readDps(d1, "hp-switch")
        if dps1 is not None:
            dataDict.update(remapKeys1(dps1))

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

