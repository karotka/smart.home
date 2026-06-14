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

#d = tinytuya.CoverDevice(dev_id="bf804257239825cfb7xyjf", address="192.168.0.166", local_key="ev3RL.NU^8tqWSz@", version="3.3")
d = tinytuya.OutletDevice(dev_id="bf06f140ee20807fdaalyq",  address="192.168.0.191", version="3.3")
d.set_socketTimeout(2)
d.set_socketRetryLimit(0)
payload = d.generate_payload(tinytuya.DP_QUERY)

d1 = tinytuya.OutletDevice(dev_id="bf2f6c60f5d1b15d9c6urw", address="192.168.0.16", version="3.4")
d1.set_socketTimeout(2)
d1.set_socketRetryLimit(0)


def _readDps(device, label, send_payload=None):
    """status() with the timeout we just configured, plus a graceful
    fallback when the device returns no `dps` (offline / wrong key /
    Tuya error response)."""
    try:
        if send_payload is not None:
            device.send(send_payload)
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

        dps = _readDps(d, "hp", send_payload=payload)
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

