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

broker_address="192.168.0.224"
pidfile = "/tmp/mqtt.feeder.pid"

mqttClient = mqtt.Client("P1") #create new instance

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
    handler = RotatingFileHandler("/root/smart.home/invertor/log/mqtt.feeder_log", backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()



def write(dt, period):

    # write invertor actual data for online monitoring
    client = getClient()
    mqClient = getMqttClient()

    dataDict = dict()

    if period  == "hour":
        # get all months
        df = client.query("select * from invertor_monthly")
        dataDict["columns"] = df["invertor_monthly"].columns.values
        dataDict["values"] = df["invertor_monthly"].values
        mqttClient.publish("home/invertor/0/monthly/rows", json.dumps(dataDict, cls=Encoder), qos=1, retain=True)

    elif period  == "minute":
        # get last 7 days
        df = client.query("select sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut,  sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn from invertor_daily where time > now() - 7d group by time(1d)")
        dataDict["columns"] = df["invertor_daily"].columns.values
        dataDict["values"] = df["invertor_daily"].fillna(0).values
        mqttClient.publish("home/invertor/0/last7/rows/", json.dumps(dataDict, cls=Encoder), qos=1, retain=True)

    else:
        # get invertor status
        df = client.query("select * from invertor_status order by time desc limit 1")
        dataDict["status"] = df["invertor_status"].iloc[0].to_dict()
        # actual
        df = client.query("select *  from invertor_actual order by time desc limit 1")
        dataDict["actual"] = df["invertor_actual"].iloc[0].to_dict()

        mqClient.publish("home/invertor/0/actual/", json.dumps(dataDict["actual"], cls=Encoder), qos=1, retain=True)
        mqClient.publish("home/invertor/0/status/", json.dumps(dataDict["status"], cls=Encoder), qos=1, retain=True)

    logging.info("Send <%s> data to mqtt broker ok time: %s" % (period, dt))


oldMinute = 0
oldHour = 0
try:
    while True:
        dt = pd.to_datetime('today').now()
        minute = dt.minute
        hour = dt.hour
        
        if oldHour != hour:
            write(dt, "hour")

        if oldMinute != minute:
            write(dt, "minute")
        
        write(dt, "actual")
        time.sleep(3)

        oldMinute = minute
        oldHour = hour

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)

