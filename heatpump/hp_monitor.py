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
        "108" : "watterTankTemperature",
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
        "108" : "watterTankTemperature",
        "109" : "openingOfMainEEV",
        "111" : "openingOfAssistantEEV",
        "112" : "compresorCurrent",
        "113" : "heatSinkTemperature",
        "114" : "DCBusVoltage",
        "115" : "compresorFrequency",
        "116" : "windSpeedFan1"
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
    handler = RotatingFileHandler("/root/smart.home/heatpump/log/hp_log", backupCount=5)
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
    dt = pd.to_datetime('today').now()
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

#d = tinytuya.CoverDevice(dev_id="bf804257239825cfb7xyjf", address="192.168.0.166", local_key="ev3RL.NU^8tqWSz@", version="3.3")
d = tinytuya.OutletDevice(dev_id="bf06f140ee20807fdaalyq", address="192.168.0.191", version="3.3")
payload = d.generate_payload(tinytuya.DP_QUERY)


try:

    while True:
        d.send(payload)
        data = d.status()
        #print (pprint.pformat(remapAllKeys(data["dps"]), compact=True).replace("'",'"') )
        dataDict = remapKeys(data["dps"])
        #print (pprint.pformat(dataDict, compact=True).replace("'",'"') )
        #print ("---")
        writeDb(dataDict)
        time.sleep(5)

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)

