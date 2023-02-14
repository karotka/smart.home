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

elif mode == "daily":
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        print (e)
        sys.exit(0)
    day = (dt + relativedelta(days=1)).strftime("%Y-%m-%d")
    dayPast = dt.strftime("%Y-%m-%d")

elif mode == "monthly":
    dt = datetime.strptime("%s-01" % date, "%Y-%m-%d")
    month = date
    nextMonth = (dt + relativedelta(months=1)).strftime("%Y-%m-%d")

#print ("day: %s pass: %s" % (day, dayPast))

config = configparser.ConfigParser()
config.read('/home/pi/smart.home/invertor/conf/config.ini')


def createLog():
    """
    Creates a rotating log
    """
    handler = RotatingFileHandler("/home/pi/smart.home/invertor/log/aggregate_log", backupCount=5)
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


def getMonthlyRows(fromStr, toStr, columns = "*"):
    tzshift = datetime.now().astimezone().tzinfo.utcoffset(None).seconds * 1e9

    fr = datetime.strptime(fromStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    to = datetime.strptime(toStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    query = "select %s from invertor where time > %d and time <= %d" % (
            ",".join(columns), fr, to)
    logging.debug(query)
    return client.query(query)


def dropMonthlyRows(fromStr):
    tzshift = datetime.now().astimezone().tzinfo.utcoffset(None).seconds * 1e9

    fr = datetime.strptime("%s-01" % fromStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    to = fr + 1440*1e9
    query = "delete from invertor_monthly where time > %d and time <= %d" % (fr, to)
    logging.debug(query)
    client.query(query)


def dropDailyRows(fromStr, toStr):
    tzshift = datetime.now().astimezone().tzinfo.utcoffset(None).seconds * 1e9

    fr = datetime.strptime(fromStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    to = datetime.strptime(toStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    query = "delete from invertor_monthly where time > %d and time <= %d" % (fr, to)
    logging.debug(query)
    client.query(query)


def getDailyRows(fromStr, toStr, columns = "*"):
    tzshift = datetime.now().astimezone().tzinfo.utcoffset(None).seconds * 1e9

    fr = datetime.strptime(fromStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    to = datetime.strptime(toStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    query = "select %s from invertor where time > %d and time <= %d" % (
            ",".join(columns), fr, to)
    logging.debug(query)
    return client.query(query)


if mode == "daily":
    logging.info("Aggregate %s data for %s" % (mode, dayPast))
    df = getDailyRows(dayPast, day, columns = columns)

    df = df["invertor"].reset_index()
    df["batteryPowerIn"] = df["batteryCurrent"] * df["batteryVoltage"]
    df["batteryPowerOut"] = df["batteryDischargeCurrent"] * df["batteryVoltage"]
    df["solarPowerIn"] = df["solarCurrent"] * df["solarVoltage"]
    df["time"] = df["index"].dt.date
    df["hour"] = df["index"].dt.hour
    
    di = {
        "time" : df["time"],
        "hour" : df["hour"],
        "deviceNumber" : df["deviceNumber"],
        "outputPowerApparent" : df["outputPowerApparent"],
        "outputPowerActive" : df["outputPowerActive"],
        "solarPowerIn" : df["solarPowerIn"],
        "batteryPowerIn" : df["batteryPowerIn"],
        "batteryPowerOut" : df["batteryPowerOut"]
    }
    di = pd.DataFrame(di)
    di = di.groupby(["time", "hour", "deviceNumber"]).mean()
    di = di.groupby(["time"]).sum().reset_index()
    di["time"] = pd.to_datetime(di['time'])
    di = di.set_index("time")
    di["solarPowerIn"] = di["solarPowerIn"].astype(int)
    
    dropDailyRows(dayPast, day)

    client.write_points(di, 'invertor_daily', protocol = 'line')
    logging.info("Done ....")


if mode == "monthly":
    logging.info("Aggregate %s data for %s" % (mode, month))
    df = getMonthlyRows('%s-01' % month, nextMonth, columns = columns)

    df = df["invertor"]
    df["batteryPowerIn"] = df["batteryCurrent"] * df["batteryVoltage"]
    df["batteryPowerOut"] = df["batteryDischargeCurrent"] * df["batteryVoltage"]
    df["solarPowerIn"] = df["solarCurrent"] * df["solarVoltage"]

    di = {
        "time" : pd.to_datetime("%s-01" % month, format = "%Y-%m-%d"),
        "deviceNumber" : [df["deviceNumber"].max()],
        "outputPowerApparent" : [df["outputPowerApparent"].sum() / 60000],
        "outputPowerActive" : [df["outputPowerActive"].sum() / 60000],
        "solarPowerIn" : [df["solarPowerIn"].sum() / 60000],
        "batteryPowerIn" : [df["batteryPowerIn"].sum() / 60000],
        "batteryPowerOut" : [df["batteryPowerOut"].sum() / 60000]
    }

    dfDb = pd.DataFrame(di).set_index("time")
    dropMonthlyRows(month)

    client.write_points(dfDb, 'invertor_monthly', protocol = 'line')
    logging.info("Done ....")

