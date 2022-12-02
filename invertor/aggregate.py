import os
import time
from influxdb import DataFrameClient, InfluxDBClient
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
import sys

try:
    month = sys.argv[1:][0].strip()
except IndexError as e:
    sys.exit(1)

dt = datetime.strptime("%s-01" % month, "%Y-%m-%d")
nextMonth = (dt + relativedelta(months=1)).strftime("%Y-%m-%d")

def getClient():
    return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')


client = getClient()

columns = [
    "deviceNumber", "batteryCurrent", "batteryDischargeCurrent",
    "batteryVoltage", "gridVoltage", "outputPowerActive",
    "outputPowerApparent", "outputVoltage", "solarCurrent", "solarVoltage"]


def getRows(fromStr, toStr, columns = "*"):
    tzshift = datetime.now().astimezone().tzinfo.utcoffset(None).seconds * 1e9

    fr = datetime.strptime(fromStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    to = datetime.strptime(toStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    query = "select %s from invertor where time > %d and time <= %d" % (
            ",".join(columns), fr, to)
    print (query)

    return client.query(query)


def dropRows(fromStr):
    tzshift = datetime.now().astimezone().tzinfo.utcoffset(None).seconds * 1e9

    fr = datetime.strptime("%s-01" % fromStr, "%Y-%m-%d").timestamp()*1e9 + tzshift
    to = fr + 1440*1e9
    query = "delete from invertor_monthly where time > %d and time <= %d" % (fr, to)
    print (query)
    print (client.query(query))


df = getRows('%s-01' % month, nextMonth, columns = columns)

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
print (dfDb)
dropRows(month)

client.write_points(dfDb, 'invertor_monthly', protocol = 'line')




