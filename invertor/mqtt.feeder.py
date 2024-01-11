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

broker_address="192.168.0.224"
pidfile = "/tmp/mqtt.feeder.pid"

mqttClient = mqtt.Client("feeder") #create new instance

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
        print ("new connection")
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
    handler = RotatingFileHandler("/home/pi/smart.home/invertor/log/mqtt.feeder_log", backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()



rooms = {
    10178502 : "obyvak",
    10243897 : "temperature",
    10202255 : "petr",
    10200594 : "koupelna",
    10204017 : "loznice",
    10246875 : "vchod",
    10178453 : "kluci",
    10040010 : "garaz"}

def write(dt, period):

    # write invertor actual data for online monitoring
    client = getClient()
    mqClient = getMqttClient()

    dataDict = dict()

    if period  == "hour":
        # get all months
        df = client.query("select solarPowerIn from invertor_monthly where time > now() - 365d")
        #dataDict["columns"] = df["invertor_monthly"].columns.values
        dataDict["values"] = df["invertor_monthly"].values
        mqttClient.publish("home/invertor/monthly/rows/", json.dumps(dataDict, cls=Encoder), qos=1, retain=True)
        
        logging.info("Send <%s> data to mqtt broker ok" % (period, ))

    elif period  == "minute":
        # get last x days
        df = client.query("select sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut,  sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn from invertor_daily where time > now() - 13d group by time(1d)")
        dataDict["columns"] = df["invertor_daily"].columns.values
        dataDict["values"] = df["invertor_daily"].fillna(0).values[1:]
        mqttClient.publish("home/invertor/daily/rows/", json.dumps(dataDict, cls=Encoder), qos=1, retain=True)


        for id, name in rooms.items():

            try:
                df = client.query("select last(temperature) as temp from sensor where sensorId=%s" % (id))
                #logging.info("%s" % (df["sensor"]["temp"].values[0], ))
                mqttClient.publish("home/temp/%s/" % name, json.dumps(df["sensor"]["temp"].values[0], cls=Encoder), qos=1, retain=True)
            except Exception as e:
                logging.error("Key %s not found <%s>" % (name, id))

        logging.info("Send <%s> data to mqtt broker ok" % (period, ))

    else:
        try:
            # get invertor status
            df = client.query("select * from invertor_status order by time desc limit 1")
            dataDict["status"] = df["invertor_status"].iloc[0].to_dict()

            # actual string 1
            df1 = client.query("select batteryCurrent, batteryDischargeCurrent, batteryVoltage, batteryVoltageSCC, busVoltage, deviceNumber, loadPercent, outputFreq, outputPowerActive, outputPowerApparent, outputVoltage, solarCurrent, solarVoltage, temperature, gridFreq, gridVoltage from invertor_actual where deviceNumber = 'first' order by time desc limit 1")

            # actual string 2
            df2 = client.query("select batteryCurrent, batteryDischargeCurrent, batteryVoltage, batteryVoltageSCC, busVoltage, deviceNumber, loadPercent, outputFreq, outputPowerActive, outputPowerApparent, outputVoltage, solarCurrent, solarVoltage, temperature, gridFreq, gridVoltage from invertor_actual where deviceNumber = 'second' order by time desc limit 1")

            try:
                bc1 = df1["invertor_actual"].batteryCurrent
                bc2 = df2["invertor_actual"].batteryCurrent

                dataDict["invertor2"] = df2["invertor_actual"].iloc[0].to_dict()
                dataDict["invertor1"] = df1["invertor_actual"].iloc[0].to_dict()
            except Exception as e:
                logging.error("%s" % (e, ))
                return

            mqttClient.publish("home/invertor/actual/", json.dumps(dataDict, cls=Encoder), qos=1, retain=True)

            logging.info("Send <%s> data to mqtt broker ok" % (period, ))

        except Exception as e:
            logging.error("Exception: %s" % (traceback.format_exc(), ))


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
