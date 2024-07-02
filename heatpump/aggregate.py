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
        day = datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        print (e)
        sys.exit(0)


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


#print ("day: %s mode: %s" % (day, mode))

def getHourlyRows(day):
    query = "delete from hp_hourly where time > now() - 24h"
    client.query(query)
    query = (
        "select \
             MEAN(ambientTemperature) AS ambientTemperature,\
             MEAN(compresorCurrent) AS compresorCurrent,\
             MEAN(compresorFrequency) AS compresorFrequency,\
             MEAN(coolingCoilTemperature) AS coolingCoilTemperature,\
             MEAN(current) AS current,\
             MEAN(evaporatorCoilTemperature) AS evaporatorCoilTemperature,\
             MEAN(exhaustGasTemperature) AS exhaustGasTemperature,\
             MEAN(heatSinkTemperature) AS heatSinkTemperature,\
             MEAN(openingOfAssistantEEV) AS openingOfAssistantEEV,\
             MEAN(openingOfMainEEV) AS openingOfMainEEV,\
             MEAN(power) AS power,\
             MEAN(returnGasTemperature) AS returnGasTemperature,\
             MEAN(voltage) AS voltage,\
             MEAN(waterInletTemperature) AS waterInletTemperature,\
             MEAN(waterOutletTemperature) AS waterOutletTemperature,\
             MEAN(waterTankTemperature) AS waterTankTemperature,\
             MEAN(windSpeedFan1) AS windSpeedFan1\
        from hp where time > now() - 24h group by time(1h) order by time desc")
    #logging.debug(query)
    return client.query(query)

if mode == "hourly":

    data = getHourlyRows(day)
    data = data["hp"].reset_index().set_index(["index"])
    #print (data)
    
    logging.info("Aggregate %s data for day %s" % (mode, day))

    client.write_points(data, 'hp_hourly',  protocol = 'line')
    logging.info("Done .... ")



