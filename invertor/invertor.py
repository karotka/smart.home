#!/usr/bin/python

import os
import sys
import serial
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import datetime
import daemon
from influxdb import DataFrameClient
from crc16pure import crc16xmodem


QID = b'QID\x18\x0b\r'
QPIGS = b'QPIGS\xb7\xa9\r'
QPIRI = b'QPIRI\xf8T\r'
pidfile = "/tmp/invertor.pid"

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
    handler = RotatingFileHandler("/home/karotka/log/invertor_log", backupCount=5)
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
        self.status              = None
        self.warning             = None
        self.gs = GeneralStatus()

        self._open()


    def _open(self):
        self.serial = serial.Serial(
            port     = '/dev/ttyUSB0',
            baudrate = 2400,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            bytesize = serial.EIGHTBITS
        )
        self.serial.flushInput()
        self.serial.flushOutput()
        logging.info("Open serial port: <%s>" % self.serial)


    def reconnect(self):
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(2)
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
        self.serial.write(QID)
        data = self.call(16)
        self.deviceNumber = data[0]


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


    def setChargeCurrent(self, batteryVoltage):

        if batteryVoltage > 58.16:
            value = 10
        elif batteryVoltage > 57.9:
            value = 40
        elif batteryVoltage > 57.5:
            value = 60
        elif batteryVoltage <= 57.4:
            value = 80

        if self.gs.solarMaxChargingCurrent != value:
            v = "%s".zfill(4) % value
            ret = self.set("MNCHGC", v)[0]
            logging.info(
                "Battery voltage is: %s. Setting charge value to: %s, %s" % (
                    batteryVoltage, value, ret))


    def getGeneralStatus(self):
        self.serial.write(QPIRI)
        data = self.call(100)

        self.gs.gridVoltage = float(data[0])
        self.gs.ratedInputCurrent = float(data[1])
        self.gs.ratedAcOutputVoltage = float(data[2])
        self.gs.ratedAcOutputFrequency = float(data[3])
        self.gs.ratedOutputCurrent = float(data[4])
        self.gs.ratedAcOutputApparentPower = float(data[5])
        self.gs.ratedAcOutputActivePower = float(data[6])
        self.gs.ratedBatteryVoltage = float(data[7])
        self.gs.batteryVoltage = float(data[8])
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
        if parallelMode == 0: self.gs.parallelMode = 'No paralel'
        elif parallelMode == 1: self.gs.parallelMode = 'Single phase'
        elif parallelMode == 2: self.gs.parallelMode = '3P1'
        elif parallelMode == 3: self.gs.parallelMode = '3P2'
        elif parallelMode == 4: self.gs.parallelMode = '3P3'

        self.gs.batteryVoltageHighEndInverterSwitching = 48 + int(float(data[22]))

        solarWorkingConditionsParallel = int(data[23])
        if solarWorkingConditionsParallel == 0: self.gs.solarWorkingConditionsParallel = 'ONE'
        elif solarWorkingConditionsParallel == 1: self.gs.solarWorkingConditionsParallel = 'ALL'

        automaticAdjustmentSolarMaximumChargingPower = int(data[24])
        if automaticAdjustmentSolarMaximumChargingPower == 0:
            self.gs.automaticAdjustmentSolarMaximumChargingPower = 'According to load'
        elif automaticAdjustmentSolarMaximumChargingPower == 1:
            self.gs.automaticAdjustmentSolarMaximumChargingPower = 'Battery maximum'

        return self.gs


inv = Invertor()
lastBatteryChargeCurrent = 0

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
    return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')


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
    gs = inv.getGeneralStatus()
    inv.setChargeCurrent(batteryVoltage)

    df1 = pd.DataFrame(gs.__dict__, index=[0])
    df1["time"] = dt
    df1.set_index(['time'], inplace = True)
    client.write_points(df1, 'invertor_status', protocol = 'line')


lastMinute = -1
cr = 0

try:
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

        if minute == lastMinute:
            dfAll = dfAll.append(df)
        else:
            if lastMinute != -1:
                writeToDb(dfAll, dt)

            dfAll = df

        lastMinute = minute

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)

