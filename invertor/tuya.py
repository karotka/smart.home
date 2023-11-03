#!/usr/bin/python

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import datetime
from influxdb import DataFrameClient
import paho.mqtt.client as mqtt 
import json
import numpy as np
import traceback
import tinytuya

broker_address="192.168.0.224"
pidfile = "/tmp/tuya.pid"

mqttClient = mqtt.Client("Tuya") #create new instance


class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(Encoder, self).default(obj)

def getMqttClient():
    if not mqttClient.is_connected():
        mqttClient.connect(broker_address) #connect to broker
    return mqttClient

def getClient():
    while True:
        try:
            return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')
        except:
            logging.error(e, exc_info = True)
            time.sleep(3)


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
    handler = RotatingFileHandler("/root/smart.home/invertor/log/tuya_log", backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


def gridOff(bv):
    GRID_DEVICE = tinytuya.OutletDevice(dev_id="bf804257239825cfb7xyjf", address="192.168.0.166", version="3.3")
    payload = GRID_DEVICE.generate_payload(tinytuya.DP_QUERY)
    GRID_DEVICE.send(payload)
    data = GRID_DEVICE.status()
    if data.get("dps").get("1") == True:
        GRID_DEVICE.turn_off()
        logging.info("Battery volatge is <%sV>, turn it off" % bv)
    else:
        logging.info("Battery voltage is <%sV> leave the switch off" % (bv,))


def gridOn(bv):
    GRID_DEVICE = tinytuya.OutletDevice(dev_id="bf804257239825cfb7xyjf", address="192.168.0.166", version="3.3")
    payload = GRID_DEVICE.generate_payload(tinytuya.DP_QUERY)
    GRID_DEVICE.send(payload)
    data = GRID_DEVICE.status()
    if data.get("dps").get("1") == False:
        GRID_DEVICE.turn_on()
        logging.info("Battery volatge is <%sV>, turn it on" % bv)
    else:
        logging.info("Battery voltage is <%sV> leave the switch on" % (bv,))


def doIt(dt, period, data):

    # pouze, pokud se nabiji baterie
    #if batteryCurrent, batteryDischargeCurrent > 0 \
    #    # a napeti baterie je vetsi nez 50V
    #    and batteryVoltage > 50:
    #    pass

    d = data["invertor1"]
    batteryVoltage = float(d["batteryVoltage"])
  
    # case odpojit CEZ
    if batteryVoltage > 49.5:
        gridOff(batteryVoltage)

    # case pripojit CEZ
    elif batteryVoltage < 48.5:
        gridOn(batteryVoltage)

    else:
        gridOff(batteryVoltage)



def on_connect(client, userdata, flags, rc):
    #print(f"Connected with result code {rc}")
    client.subscribe("home/invertor/actual/")


oldMinute = 0
oldHour   = 0
def on_message(client, userdata, msg):
    global oldMinute
    global oldHour

    dt = pd.to_datetime('today').now()
    minute = dt.minute
    hour = dt.hour

    # one time per hour
    #if oldHour != hour:
    #    doIt(dt, "hour", msg.payload)

    # one time per minute
    try:
        if oldMinute != minute:
            logging.info("Recv. minute message: %s" % (dt,))
            doIt(dt, "minute", json.loads(msg.payload))

        #doIt(dt, "actual", json.loads(msg.payload))

    except Exception as e:
        print ("aaaa")
        logging.error("Exception occurred", exc_info = True)

    oldMinute = minute
    oldHour = hour

try:
    client = mqtt.Client("tuya-client") # client ID "mqtt-test"
    client.on_connect = on_connect
    client.on_message = on_message
    #client.username_pw_set("myusername", "aeNg8aibai0oiloo7xiad1iaju1uch")
    client.connect(broker_address, 1883)
    client.loop_forever()  # Start networking daemon

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)
