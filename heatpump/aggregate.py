#!/usr/bin/python3

import os
import time
import configparser
import logging
from influxdb import DataFrameClient, InfluxDBClient
from datetime import datetime
from dateutil.relativedelta import relativedelta
from logging.handlers import RotatingFileHandler
import pandas as pd
import getopt
import sys

modes = ("hourly", "daily", "monthly")

try:
    args = sys.argv[1:]
    opts, args = getopt.getopt(args, "m:d", ["mode=", "date="])
except IndexError as e:
    sys.exit(1)


for opt, arg in opts:
    if opt in ['-m', '--mode']:
        mode = arg
        if mode not in modes:
            print ("Mode has to be in: %s", modes)
            sys.exit(0)

    elif opt in ('-d', '--date'):
        date = arg

if mode == "hourly":
    try:
        dt = datetime.strptime(date, "%Y-%m-%d %H")
    except ValueError as e:
        print (e)
        sys.exit(0)
    hour = (dt + relativedelta(hours=1)).strftime("%Y-%m-%d %H")
    hourPast = dt.strftime("%Y-%m-%d %H")


#print ("day: %s pass: %s" % (day, dayPast))

config = configparser.ConfigParser()
config.read('/home/pi/smart.home/heatpump/conf/config.ini')


def createLog():
    """
    Creates a rotating log
    """
    handler = RotatingFileHandler("/home/pi/smart.home/heatpump/log/aggregate_log", backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s aggregate [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


def getClient():
    return DataFrameClient(
            config['InfluxDb']['Host'],
            int(config['InfluxDb']['Port']),
            config['InfluxDb']['User'],
            config['InfluxDb']['Password'],
            config['InfluxDb']['Db'])


client = getClient()

columns = [
    "deviceNumber", "batteryCurrent", "batteryDischargeCurrent",
    "batteryVoltage", "gridVoltage", "outputPowerActive",
    "outputPowerApparent", "outputVoltage", "solarCurrent", "solarVoltage"]


if mode == "hourly":

    dropHourlyRows(day)

    for invertor in ["first", "second"]:
        logging.info("Aggregate %s data for %s, %s" % (mode, dayPast, invertor))
        df = getDailyRows(dayPast, day, invertor, columns = columns)

        df = df["invertor"].reset_index()
        df["batteryPowerIn"] = df["batteryCurrent"] * df["batteryVoltage"]
        df["batteryPowerOut"] = df["batteryDischargeCurrent"] * df["batteryVoltage"]
        df["solarPowerIn"] = df["solarCurrent"] * df["solarVoltage"]
        df["time"] = df["index"].dt.date
        df["hour"] = df["index"].dt.hour
    
        di = {
            "time" : df["time"],
            "hour" : df["hour"],
            "outputPowerApparent" : df["outputPowerApparent"],
            "outputPowerActive" : df["outputPowerActive"],
            "solarPowerIn" : df["solarPowerIn"],
            "batteryPowerIn" : df["batteryPowerIn"],
            "batteryPowerOut" : df["batteryPowerOut"]
        }
        di = pd.DataFrame(di)
        di = di.groupby(["time", "hour"]).mean()
        di = di.groupby(["time"]).sum().reset_index()
        di["time"] = pd.to_datetime(di['time'])
        di = di.set_index(["time"])
        di["solarPowerIn"] = di["solarPowerIn"].astype(int)
        di["outputPowerApparent"] = di["outputPowerApparent"].astype(int)
        di["outputPowerActive"] = di["outputPowerActive"].astype(int)
        di["batteryPowerIn"] = di["batteryPowerIn"].astype(int)
        di["batteryPowerOut"] = di["batteryPowerOut"].astype(int)
   
        #print (di)
        client.write_points(di, 'invertor_daily', tags = {"devNumber" : invertor}, protocol = 'line')
        logging.info("Done .... %s" % invertor)


if mode == "monthly":
    logging.info("Aggregate %s data for %s" % (mode, month))
    df = getMonthlyRows('%s-01' % month, nextMonth, columns = [
            "sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut, sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn"])
    dropMonthlyRows(month)
    client.write_points(df["invertor_daily"] / 1000, 'invertor_monthly', protocol = 'line')
    logging.info("Done ....")

