#!/usr/bin/python

import os
import sys
import time
import pickle
import logging
import configparser
from logging.handlers import RotatingFileHandler

import serial
import redis
import pandas as pd
from influxdb import DataFrameClient
from crc16pure import crc16xmodem

QID   = b'QID\x18\x0b\r'
QMOD  = b'QMODI\xc1\r'
QPIGS = b'QPIGS\xb7\xa9\r'
QPIRI = b'QPIRI\xf8T\r'

# Fields returned by QPIGS in order — used both for parsing the inverter
# response and for building the DataFrame in the main loop.
QPIGS_FIELDS = [
    "gridVoltage", "gridFreq", "outputVoltage", "outputFreq",
    "outputPowerApparent", "outputPowerActive", "loadPercent", "busVoltage",
    "batteryVoltage", "batteryCurrent", "batteryCapacity", "temperature",
    "solarCurrent", "solarVoltage", "batteryVoltageSCC", "batteryDischargeCurrent",
]

position = sys.argv[1]

# Per-device configuration. Serial port falls back to /dev/ttyUSB0 when the
# preferred port is missing (hosts with only one USB-serial adapter).
DEVICE_CONFIG = {
    'first':  {'port': '/dev/ttyUSB0', 'redis_key': 'invertor_1'},
    'second': {'port': '/dev/ttyUSB1', 'redis_key': 'invertor_2'},
    'third':  {'port': '/dev/ttyUSB2', 'redis_key': 'invertor_3'},
    'fourth': {'port': '/dev/ttyUSB3', 'redis_key': 'invertor_4'},
    'proto':  {'port': '/dev/ttyUSB0', 'redis_key': 'invertor_1'},
}

config = configparser.ConfigParser()
config.read("/home/pi/smart.home/invertor/conf/config.ini")

pidfile = "/tmp/invertor_%s.pid" % position
redisConn = None


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
        self.deviceNumber = 0
        self.workingStatus = ""
        self.warning = None
        for name in QPIGS_FIELDS:
            setattr(self, name, 0)
        self.gs = GeneralStatus()
        self._open()


    def _open(self):
        port = DEVICE_CONFIG[position]['port']
        if not os.path.exists(port):
            port = '/dev/ttyUSB0'

        self.serial = serial.Serial(
            port     = port,
            baudrate = 2400,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            bytesize = serial.EIGHTBITS
        )

        self.serial.flushInput()
        self.serial.flushOutput()
        logging.info("Open serial: <%s>" % self.serial)


    def reconnect(self):
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(1)
        self._open()


    def call(self, length):
        data = list()
        while 1:
            line = self.serial.read(1)
            data.append(line.decode('utf-8', 'ignore'))
            if ord(line) == 13:
                data = "".join(data)
                data = data[1:length].split(" ")
                if not data[0]:
                    self.reconnect()
                break
        return data


    def refreshData(self):
        self.deviceNumber = position

        self.serial.write(QMOD)
        self.workingStatus = self.call(2)[0]

        self.serial.write(QPIGS)
        data = self.call(117)
        for i, name in enumerate(QPIGS_FIELDS):
            setattr(self, name, data[i])


    def set(self, command, value):
        com = ('%s%s' % (command, value)).encode(encoding='UTF-8')
        data = com + crc16(com) + b'\r'
        ret = self.serial.write(data)
        return self.call(ret)


    def setChargeCurrent(self, batteryVoltage):
        """Set charge current according to battery voltage."""
        if batteryVoltage > 57:
            value = 10
        elif batteryVoltage > 56.8:
            value = 20
        elif batteryVoltage > 56.5:
            value = 40
        else:
            value = 70

        v = "%s".zfill(4) % value
        ret = self.set("MNCHGC", v)[0]
        logging.info(
            "Battery voltage is: %s. Charge current is: %s, setting charge value to: %s, %s" % (
            batteryVoltage, self.gs.solarMaxChargingCurrent, value, ret))


    def getGeneralStatus(self):
        """Get invertor params via QPIRI."""
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


columns = ["deviceNumber"] + QPIGS_FIELDS


def getClient():
    return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor',
                           timeout=5, retries=2)


def getRedisClient():
    global redisConn
    try:
        redisConn.ping()
    except Exception:
        try:
            host = config["Redis"].get("host")
            port = int(config["Redis"].get("port"))
            redisConn = redis.Redis(host, port)
        except Exception:
            return None
    return redisConn


def _prepDf(df, dt):
    """Aggregate by deviceNumber, round, and index by time — common to both writers."""
    df = df.set_index(['deviceNumber']).groupby(['deviceNumber']).mean().round(1).reset_index()
    df["time"] = dt
    df.set_index(['time'], inplace=True)
    return df


def writeToDb(df, dt, deviceNumber):
    df = _prepDf(df, dt)

    # Battery regulation runs before InfluxDB so a network hiccup never
    # leaves the inverter on a stale charge current.
    batteryVoltage = df.iloc[0]["batteryVoltage"]
    gsDict = inv.getGeneralStatus().__dict__
    inv.setChargeCurrent(batteryVoltage)

    try:
        client = getClient()
        client.write_points(df, 'invertor', protocol='line')
        logging.info("Send data ok time: %s, device number: %s" % (dt, deviceNumber))
        client.query("delete from invertor_status where time < now() -1h")
        df1 = pd.DataFrame(gsDict, index=[0])
        df1["time"] = dt
        df1.set_index(['time'], inplace=True)
        client.write_points(df1, 'invertor_status', protocol='line')
    except Exception as e:
        logging.error("InfluxDB write failed in writeToDb: %s", e)

    return gsDict


def writeDb(df, dt, dataDict, deviceNumber):
    """Write fresh values for live monitoring."""
    df = _prepDf(df, dt)

    dataDict["last"] = dict()
    try:
        client = getClient()
        client.write_points(df, 'invertor_actual', protocol='line')
        client.query("delete from invertor_actual where time < now() -1h")

        qdf = client.query("select sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut, sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn from invertor_daily where time > now() - 24h")
        try:
            dataDict["last"] = qdf["invertor_daily"].iloc[0].to_dict()
        except Exception:
            pass
        logging.info("Send data to invertor actual ok time: %s, device number: %s" % (dt, deviceNumber))
    except Exception as e:
        logging.error("InfluxDB write failed in writeDb: %s", e)

    # Redis update happens even on InfluxDB failure so the web UI keeps live data.
    redisClient = getRedisClient()
    if redisClient:
        redisClient.set(DEVICE_CONFIG[position]['redis_key'], pickle.dumps(dataDict))

    del dataDict["last"]


lastMinute = -1
try:
    gsDict = inv.getGeneralStatus().__dict__
    while True:
        dt = pd.Timestamp.now(tz='Europe/Prague')
        minute = dt.minute
        inv.refreshData()

        row = [inv.deviceNumber] + [float(getattr(inv, f)) for f in QPIGS_FIELDS]
        df = pd.DataFrame([row], columns=columns)

        gsDict.update(df.iloc[0].to_dict())
        gsDict["workingStatus"] = inv.workingStatus

        writeDb(df, dt, gsDict, inv.deviceNumber)

        if minute == lastMinute:
            dfAll = dfAll.append(df)
        else:
            if lastMinute != -1:
                gsDict = writeToDb(dfAll, dt, inv.deviceNumber)
            dfAll = df

        lastMinute = minute

except Exception as e:
    logging.error("Exception occurred", exc_info=True)

finally:
    os.unlink(pidfile)

