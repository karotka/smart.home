#!/usr/bin/python

import os
import sys
import serial
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import datetime
import pickle
import daemon
import redis
import configparser
import json
#import paho.mqtt.client as mqtt #import the client1
from influxdb import DataFrameClient
from crc16pure import crc16xmodem
from datetime import timedelta

QID   = b'QID\x18\x0b\r'
QMOD  = b'QMODI\xc1\r'
QPIGS = b'QPIGS\xb7\xa9\r'
QPIRI = b'QPIRI\xf8T\r'

position = sys.argv[1]

config = configparser.ConfigParser()
config.read("/home/pi/smart.home/invertor/conf/config.ini")

pidfile = "/tmp/invertor_%s.pid" % position
redisConn = None
broker_address="192.168.0.224"

#mqttCounter = 0

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
    handler = RotatingFileHandler("/home/pi/smart.home/invertor/log/invertor_%s_log" % position, backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


def crc16(data):
    return crc16xmodem(data).to_bytes(2, 'big')


class GeneralStatus:
    pass


class Invertor:

    def __init__(self):
        self.deviceNumber        = 0
        self.gridVoltage         = 0.0
        self.gridFreq            = 0.0
        self.outputVoltage       = 0.0
        self.outputFreq          = 0
        self.outputPowerApparent = 0
        self.outputPowerActive   = 0
        self.loadPercent         = 0.0
        self.busVoltage          = 0.0
        self.batteryVoltage      = 0.0
        self.batteryCurrent      = 0.0
        self.batteryCapacity     = 0
        self.temperature         = 0
        self.solarCurrent        = 0.0
        self.solarVoltage        = 0
        self.batteryVoltageSCC   = 0
        self.batteryDischargeCurrent = 0
        self.workingStatus       = ""
        self.warning             = None
        self.gs = GeneralStatus()

        self._open()


    def _open(self):
        if position == 'first' or position == "proto":
            port     = '/dev/ttyUSB0'
        elif position == 'second':
            port     = '/dev/ttyUSB1'

        self.serial = serial.Serial(
            port     = port,
            baudrate = 2400,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            bytesize = serial.EIGHTBITS
        )
        logging.info("Open serial: <%s>" % self.serial)


    def reconnect(self):
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(2)
            self.serial.flushInput()
            self.serial.flushOutput()
            time.sleep(1)
        self._open()


    def call(self, length):
        data = list()
        while 1:
            line = self.serial.read(1)
            #print (line)
            data.append(line.decode('utf-8', 'ignore'))
            if ord(line) == 13:
                data = "".join(data)
                data = data[1:length].split(" ")
                #print(data)
                if not data[0]:
                    #print ("reconnect")
                    self.reconnect()
                break
        return data


    def refreshData(self):
        # Asking for  serial number
        #self.serial.write(QID)
        #data = self.call(16)
        if self.serial.port == "/dev/ttyUSB0":
            self.deviceNumber = 'first'
            #self.deviceNumber = 'proto'
        elif self.serial.port == "/dev/ttyUSB1":
            self.deviceNumber = 'second'
        elif self.serial.port == "/dev/ttyUSB2":
            self.deviceNumber = 'third'
        elif self.serial.port == "/dev/ttyUSB3":
            self.deviceNumber = 'fourth'

        self.serial.write(QMOD)
        data = self.call(2)
        self.workingStatus = data[0]


        # Asking for data
        self.serial.write(QPIGS)
        data = self.call(117)
        self.gridVoltage         = data[0]
        self.gridFreq            = data[1]
        self.outputVoltage       = data[2]
        self.outputFreq          = data[3]
        self.outputPowerApparent = data[4]
        self.outputPowerActive   = data[5]
        self.loadPercent         = data[6]
        self.busVoltage          = data[7]
        self.batteryVoltage      = data[8]
        self.batteryCurrent      = data[9]
        self.batteryCapacity     = data[10]
        self.temperature         = data[11]
        self.solarCurrent        = data[12]
        self.solarVoltage        = data[13]
        self.batteryVoltageSCC   = data[14]
        self.batteryDischargeCurrent = data[15]



    def set(self, command, value):
        crc = crc16(("%s%s" % (command, value)).encode(encoding = 'UTF-8'))
        com = ('%s%s' % (command, value)).encode(encoding = 'UTF-8')
        data = com + crc + b'\r' 
        #print (data)
        ret = self.serial.write(data)
        #print ("Ret: %s" % ret)
        return self.call(ret)


    """
    Set the charge current according to battery voltage
    """
    def setChargeCurrent(self, batteryVoltage):

        value = 60
        if batteryVoltage > 58:
            value = 10
        elif batteryVoltage > 57.8:
            value = 20
        elif batteryVoltage > 57:
            value = 40
        elif batteryVoltage > 56:
            value = 50
        #value = 10

        if self.gs.solarMaxChargingCurrent != value:
            v = "%s".zfill(4) % value
            ret = self.set("MNCHGC", v)[0]
            logging.info(
                "Battery voltage is: %s. Setting charge value to: %s, %s" % (
                    batteryVoltage, value, ret))


    """
    Get invertor params
    """
    def getGeneralStatus(self):
        self.serial.write(QPIRI)
        data = self.call(100)

        try:
            self.gs.gridVoltage = float(data[0])
        except:
            logging.info("ERROR data: <%s>" % data)
            self.reconnect()
            self.getGeneralStatus()

        self.gs.ratedInputCurrent = float(data[1])
        self.gs.ratedAcOutputVoltage = float(data[2])
        self.gs.ratedAcOutputFrequency = float(data[3])
        self.gs.ratedOutputCurrent = float(data[4])
        self.gs.ratedAcOutputApparentPower = float(data[5])
        self.gs.ratedAcOutputActivePower = float(data[6])
        self.gs.ratedBatteryVoltage = float(data[7])
        self.gs.batteryVoltageMainsSwitchingPoint = float(data[8])
        self.gs.batteryVoltageShutdown  = float(data[9])
        self.gs.batteryVoltageFastCharge  = float(data[10])
        self.gs.batteryVoltageFloating  = float(data[11])

        bt = int(data[12])
        if bt == 0: self.gs.batteryType = 'AGM'
        elif bt == 1: self.gs.batteryType = 'FLD'
        else: self.gs.batteryType = 'USE'

        self.gs.mainsMaxChargingCurrent  = int(data[13])
        self.gs.solarMaxChargingCurrent = int(data[14])

        inputRange = int(data[15])
        if inputRange == 0:
            self.gs.inputRange = 'ALP' # AAPL model 90-280V (switching time 8-20mS)
        else:
            self.gs.inputRange = 'UPS' # UPS model 170-280 (switching time 5-15

        loadPowerSourcePriority = int(data[16])
        if loadPowerSourcePriority == 0:
            self.gs.loadPowerSourcePriority = 'UTL' # UTL model (Mains priority) default
        elif loadPowerSourcePriority == 1:
            self.gs.loadPowerSourcePriority = 'SOL' # SOL model (Solar priority)
        else:
            self.gs.loadPowerSourcePriority = 'SBU' # SBU model (S solar energy 1 Battery 2 Mains 3)

        chargingSourcePriority = int(data[17])
        if chargingSourcePriority == 0:   self.gs.chargingSourcePriority = 'CUT' # utility first
        elif chargingSourcePriority == 1: self.gs.chargingSourcePriority = 'CSO' # solar first
        elif chargingSourcePriority == 2: self.gs.chargingSourcePriority = 'SUN' # solar & utility
        else: self.gs.chargingSourcePriority = 'OSO' # only solar Solar charging only

        self.gs.canBeParalleledEuquipment = int(data[18])

        parallelMode = int(data[21])
        if parallelMode == 0: self.gs.parallelMode   = 'NP'  # No paralel
        elif parallelMode == 1: self.gs.parallelMode = 'SP'  # single phase
        elif parallelMode == 2: self.gs.parallelMode = '3P1'
        elif parallelMode == 3: self.gs.parallelMode = '3P2'
        elif parallelMode == 4: self.gs.parallelMode = '3P3'

        self.gs.batteryVoltageHighEndInverterSwitching = 48 + int(float(data[22]))

        solarWorkingConditionsParallel = int(data[23])
        if solarWorkingConditionsParallel == 0: self.gs.solarWorkingConditionsParallel = 'ONE'
        elif solarWorkingConditionsParallel == 1: self.gs.solarWorkingConditionsParallel = 'ALL'

        automaticAdjustmentSolarMaximumChargingPower = int(data[24])
        if automaticAdjustmentSolarMaximumChargingPower == 0:
            self.gs.automaticAdjustmentSolarMaximumChargingPower = 'ALOAD' # According to load
        elif automaticAdjustmentSolarMaximumChargingPower == 1:
            self.gs.automaticAdjustmentSolarMaximumChargingPower = 'BMAX' # Battery maximum

        return self.gs


inv = Invertor()

columns = [
    "deviceNumber",
    "gridVoltage",
    "gridFreq",
    "outputVoltage",
    "outputFreq",
    "outputPowerApparent",
    "outputPowerActive",
    "loadPercent",
    "busVoltage",
    "batteryVoltage",
    "batteryCurrent",
    "batteryCapacity",
    "temperature",
    "solarCurrent",
    "solarVoltage",
    "batteryVoltageSCC",
    "batteryDischargeCurrent",
]

def getClient():
    while True:
        try:
            return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')
        except:
            logging.error(e, exc_info = True)
            time.sleep(3)


def getRedisClient():
    try:
        redisConn.ping()
    except:
        try:
            host = config["Redis"].get("host")
            port = int(config["Redis"].get("port"))
            redisConn = redis.Redis(host, port)
        except:
            return None

    return redisConn


def writeToDb(df, dt):

    df = df.set_index(['deviceNumber'])
    df = df.groupby(["deviceNumber"]).mean()
    df = df.round(1)
    df = df.reset_index()

    df["time"] = dt
    df.set_index(['time'], inplace = True)
        
    client = getClient()
    client.write_points(df, 'invertor', protocol = 'line')
    logging.info("Send data ok time: %s" % (dt))

    batteryVoltage = df.iloc[0]["batteryVoltage"]
    gsDict = inv.getGeneralStatus().__dict__
    inv.setChargeCurrent(batteryVoltage)

    client.query("delete from invertor_status where time < now() -1h")

    df1 = pd.DataFrame(gsDict, index=[0])
    df1["time"] = dt
    df1.set_index(['time'], inplace = True)
    client.write_points(df1, 'invertor_status', protocol = 'line')
    return gsDict

"""
Write fresh values sun as possible for live monitoring
"""
def writeDb(df, dt, dataDict):
    #global mqttCounter

    df = df.set_index(['deviceNumber'])
    df = df.groupby(["deviceNumber"]).mean()
    df = df.round(1)
    df = df.reset_index()

    df["time"] = dt
    df.set_index(['time'], inplace = True)
        
    # write invertor actual data for online monitoring
    client = getClient()
    client.write_points(df, 'invertor_actual', protocol = 'line')

    # delete old rows
    client.query("delete from invertor_actual where time < now() -1h")

    # get last 2 days
    df = client.query("select sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut,  sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn from invertor_daily where time > now() - 24h")
    try:
        dataDict["last"] = df["invertor_daily"].iloc[0].to_dict()
    except:
        dataDict["last"] = dict()

    # add values into the redis for smart home web
    # add invertor general setting into one dictionary
    redisClient = getRedisClient()
    #logging.info("Redis client: %s" % (redisClient))
    if redisClient:
        #logging.info("DICT: %s" % (dictionary))
        redisClient.set("invertor_1", pickle.dumps(dataDict))
        #mqttCounter = mqttCounter + 1
        #if mqttCounter == 2:
        #    client = mqtt.Client("P1") #create new instance
        #    client.connect(broker_address) #connect to broker
        #    client.publish("home/invertor/0", json.dumps(dataDict), qos=1, retain=True)#publish
        #    mqttCounter = 0


    del dataDict["last"]

    logging.info("Send data to invertor actual ok time: %s" % (dt))


lastMinute = -1
try:
    gsDict = inv.getGeneralStatus().__dict__
    while True:
        dt = pd.to_datetime('today').now()
        minute = dt.minute
        inv.refreshData()
        #logging.info("Refresh data ok time: %s" % (dt))

        df = pd.DataFrame(data = [[
            inv.deviceNumber,
            float(inv.gridVoltage),
            float(inv.gridFreq),
            float(inv.outputVoltage),
            float(inv.outputFreq),
            float(inv.outputPowerApparent),
            float(inv.outputPowerActive),
            float(inv.loadPercent),
            float(inv.busVoltage),
            float(inv.batteryVoltage),
            float(inv.batteryCurrent),
            float(inv.batteryCapacity),
            float(inv.temperature),
            float(inv.solarCurrent),
            float(inv.solarVoltage),
            float(inv.batteryVoltageSCC),
            float(inv.batteryDischargeCurrent)]], columns = columns )
        #logging.info("Minute: %s, last min %s" % (minute, lastMinute))

        
        gsDict.update(df.iloc[0].to_dict())
        gsDict["workingStatus"] = inv.workingStatus 

        writeDb(df, dt, gsDict)

        if minute == lastMinute:
            dfAll = dfAll.append(df)
        else:
            if lastMinute != -1:
                gsDict = writeToDb(dfAll, dt)

            dfAll = df

        lastMinute = minute

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)


