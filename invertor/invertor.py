#!/usr/bin/python
"""Invertor monitor — reads a PIP-series inverter over RS232,
writes per-second live data + per-minute aggregates to InfluxDB,
mirrors a live snapshot to Redis for the web UI."""

import os
import sys
import time
import pickle
import logging
import configparser
from datetime import datetime
from zoneinfo import ZoneInfo
from logging.handlers import RotatingFileHandler

import serial
import redis
from influxdb import InfluxDBClient
from crc16pure import crc16xmodem


QID   = b'QID\x18\x0b\r'
QMOD  = b'QMODI\xc1\r'
QPIGS = b'QPIGS\xb7\xa9\r'
QPIRI = b'QPIRI\xf8T\r'

# Fields returned by QPIGS, in protocol order. Used both for parsing the
# response and for building the row sent to InfluxDB / Redis.
QPIGS_FIELDS = [
    "gridVoltage", "gridFreq", "outputVoltage", "outputFreq",
    "outputPowerApparent", "outputPowerActive", "loadPercent", "busVoltage",
    "batteryVoltage", "batteryCurrent", "batteryCapacity", "temperature",
    "solarCurrent", "solarVoltage", "batteryVoltageSCC", "batteryDischargeCurrent",
]

# Per-device configuration. Serial port falls back to /dev/ttyUSB0 when the
# preferred port is missing (hosts with a single USB-serial adapter).
DEVICE_CONFIG = {
    'first':  {'port': '/dev/ttyUSB0', 'redis_key': 'invertor_1'},
    'second': {'port': '/dev/ttyUSB1', 'redis_key': 'invertor_2'},
    'third':  {'port': '/dev/ttyUSB2', 'redis_key': 'invertor_3'},
    'fourth': {'port': '/dev/ttyUSB3', 'redis_key': 'invertor_4'},
    'proto':  {'port': '/dev/ttyUSB0', 'redis_key': 'invertor_1'},
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def parseChargeStages(s):
    """Parse 'V1:A1, V2:A2, ...' into [(voltage, current), ...] sorted high→low."""
    pairs = []
    for part in s.split(','):
        v, a = part.strip().split(':')
        pairs.append((float(v), int(a)))
    pairs.sort(key=lambda p: -p[0])
    return pairs


def crc16(data):
    return crc16xmodem(data).to_bytes(2, 'big')


class GeneralStatus:
    """Bag of QPIRI-derived inverter config fields."""
    pass


class Invertor:
    """RS232 driver for the PIP-series inverter."""

    def __init__(self, position, chargeStages, chargeDefault):
        self.position = position
        self.chargeStages = chargeStages
        self.chargeDefault = chargeDefault
        self.deviceNumber = position
        self.workingStatus = ""
        self.warning = None
        for name in QPIGS_FIELDS:
            setattr(self, name, 0)
        self.gs = GeneralStatus()
        self._open()

    def _open(self):
        port = DEVICE_CONFIG[self.position]['port']
        if not os.path.exists(port):
            port = '/dev/ttyUSB0'
        self.serial = serial.Serial(
            port=port, baudrate=2400,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
        )
        self.serial.flushInput()
        self.serial.flushOutput()
        logging.info(f"Open serial: <{self.serial}>")

    def reconnect(self):
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(1)
        self._open()

    def call(self, length):
        data = []
        while True:
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
        self.deviceNumber = self.position
        self.serial.write(QMOD)
        self.workingStatus = self.call(2)[0]
        self.serial.write(QPIGS)
        data = self.call(117)
        for i, name in enumerate(QPIGS_FIELDS):
            setattr(self, name, data[i])

    def snapshot(self):
        """Current QPIGS values as {field: float} + deviceNumber."""
        row = {"deviceNumber": self.deviceNumber}
        for f in QPIGS_FIELDS:
            row[f] = float(getattr(self, f))
        return row

    def set(self, command, value):
        com = f'{command}{value}'.encode('UTF-8')
        data = com + crc16(com) + b'\r'
        ret = self.serial.write(data)
        return self.call(ret)

    def setChargeCurrent(self, batteryVoltage):
        """Set charge current according to battery voltage (stages from config)."""
        value = self.chargeDefault
        for threshold, amps in self.chargeStages:
            if batteryVoltage > threshold:
                value = amps
                break
        v = f"{value}".zfill(4)
        ret = self.set("MNCHGC", v)[0]
        logging.info(
            f"Battery voltage is: {batteryVoltage}. "
            f"Charge current is: {self.gs.solarMaxChargingCurrent}, "
            f"setting charge value to: {value}, {ret}"
        )

    def getGeneralStatus(self):
        """Get inverter config via QPIRI."""
        self.serial.write(QPIRI)
        data = self.call(100)

        try:
            self.gs.gridVoltage = float(data[0])
        except (ValueError, IndexError):
            logging.info(f"ERROR data: <{data}>")
            self.reconnect()
            return self.getGeneralStatus()

        self.gs.ratedInputCurrent = float(data[1])
        self.gs.ratedAcOutputVoltage = float(data[2])
        self.gs.ratedAcOutputFrequency = float(data[3])
        self.gs.ratedOutputCurrent = float(data[4])
        self.gs.ratedAcOutputApparentPower = float(data[5])
        self.gs.ratedAcOutputActivePower = float(data[6])
        self.gs.ratedBatteryVoltage = float(data[7])
        self.gs.batteryVoltageMainsSwitchingPoint = float(data[8])
        self.gs.batteryVoltageShutdown = float(data[9])
        self.gs.batteryVoltageFastCharge = float(data[10])
        self.gs.batteryVoltageFloating = float(data[11])

        bt = int(data[12])
        self.gs.batteryType = {0: 'AGM', 1: 'FLD'}.get(bt, 'USE')

        self.gs.mainsMaxChargingCurrent = int(data[13])
        self.gs.solarMaxChargingCurrent = int(data[14])

        self.gs.inputRange = 'ALP' if int(data[15]) == 0 else 'UPS'
        self.gs.loadPowerSourcePriority = {0: 'UTL', 1: 'SOL'}.get(int(data[16]), 'SBU')
        self.gs.chargingSourcePriority = {0: 'CUT', 1: 'CSO', 2: 'SUN'}.get(int(data[17]), 'OSO')

        self.gs.canBeParalleledEuquipment = int(data[18])

        self.gs.parallelMode = {0: 'NP', 1: 'SP', 2: '3P1', 3: '3P2', 4: '3P3'}.get(int(data[21]))

        self.gs.batteryVoltageHighEndInverterSwitching = 48 + int(float(data[22]))

        self.gs.solarWorkingConditionsParallel = 'ONE' if int(data[23]) == 0 else 'ALL'
        self.gs.automaticAdjustmentSolarMaximumChargingPower = 'ALOAD' if int(data[24]) == 0 else 'BMAX'

        return self.gs


def averageRows(rows):
    """Mean of QPIGS_FIELDS across rows; first row's deviceNumber wins."""
    out = {"deviceNumber": rows[0]["deviceNumber"]}
    for f in QPIGS_FIELDS:
        out[f] = round(sum(r[f] for r in rows) / len(rows), 1)
    return out


class Monitor:
    """Owns the inverter, sinks, and the main loop."""

    def __init__(self, position, config):
        self.position = position
        self.redisKey = DEVICE_CONFIG[position]['redis_key']
        self.config = config
        self.tz = ZoneInfo(config.get("App", "timezone", fallback="Europe/Prague"))
        self.inv = Invertor(
            position,
            parseChargeStages(config["Charge"]["stages"]),
            int(config["Charge"]["default_current"]),
        )
        self.redisConn = None
        self.gsDict = self.inv.getGeneralStatus().__dict__
        self.lastSummary = {}

    def _influx(self):
        cfg = self.config["InfluxDb"]
        return InfluxDBClient(
            cfg["Host"], int(cfg["Port"]),
            cfg["User"], cfg["Password"],
            cfg["Db"],
            timeout=5, retries=2,
        )

    def _redis(self):
        try:
            if self.redisConn is not None:
                self.redisConn.ping()
                return self.redisConn
        except Exception:
            self.redisConn = None
        try:
            host = self.config["Redis"].get("host")
            port = int(self.config["Redis"].get("port"))
            self.redisConn = redis.Redis(host, port)
            return self.redisConn
        except Exception:
            return None

    def _pushRedis(self, row):
        """Pickle merged config + live snapshot + 24h summary into Redis."""
        payload = dict(self.gsDict)
        payload.update(row)
        payload["workingStatus"] = self.inv.workingStatus
        payload["last"] = self.lastSummary
        r = self._redis()
        if r:
            r.set(self.redisKey, pickle.dumps(payload))

    def writePerSecond(self, row, dt):
        """Live values → invertor_actual + Redis."""
        try:
            client = self._influx()
            client.write_points([{
                "measurement": "invertor_actual",
                "time": dt.isoformat(),
                "fields": row,
            }])
        except Exception as e:
            logging.error(f"InfluxDB write failed (actual): {e}")
        # Redis runs even when InfluxDB is down so the UI keeps live data.
        self._pushRedis(row)

    def writePerMinute(self, minuteRows, dt):
        """Aggregate, persist long-term, refresh charge regulation + 24h summary."""
        avg = averageRows(minuteRows)

        # Battery regulation runs before InfluxDB so a network hiccup never
        # leaves the inverter on a stale charge current.
        self.gsDict = self.inv.getGeneralStatus().__dict__
        self.inv.setChargeCurrent(avg["batteryVoltage"])

        try:
            client = self._influx()
            client.write_points([{
                "measurement": "invertor",
                "time": dt.isoformat(),
                "fields": avg,
            }])
            client.write_points([{
                "measurement": "invertor_status",
                "time": dt.isoformat(),
                "fields": self.gsDict,
            }])
            # Housekeeping — once a minute is enough (was once a second).
            client.query("delete from invertor_actual where time < now() - 1h")
            client.query("delete from invertor_status where time < now() - 1h")
            # 24h summary for the Redis live tile — also moved out of the
            # per-second hot path.
            res = client.query(
                "select sum(batteryPowerIn) as batteryPowerIn, "
                "sum(batteryPowerOut) as batteryPowerOut, "
                "sum(outputPowerActive) as outputPowerActive, "
                "sum(outputPowerApparent) as outputPowerApparent, "
                "sum(solarPowerIn) as solarPowerIn "
                "from invertor_daily where time > now() - 24h"
            )
            points = list(res.get_points())
            self.lastSummary = points[0] if points else {}
            logging.info(f"Send data ok time: {dt}, device number: {avg['deviceNumber']}")
        except Exception as e:
            logging.error(f"InfluxDB write failed (minute): {e}")

    def run(self):
        lastMinute = -1
        minuteRows = []
        while True:
            dt = datetime.now(self.tz)
            self.inv.refreshData()
            row = self.inv.snapshot()
            self.writePerSecond(row, dt)
            logging.info(f"Send data to invertor actual ok time: {dt}, device number: {row['deviceNumber']}")

            minute = dt.minute
            if minute == lastMinute:
                minuteRows.append(row)
            else:
                if lastMinute != -1:
                    self.writePerMinute(minuteRows, dt)
                minuteRows = [row]
            lastMinute = minute


def createPid(pidfile):
    if os.path.isfile(pidfile):
        print(f"{pidfile} already exists, exiting")
        sys.exit()
    with open(pidfile, 'w') as f:
        f.write(str(os.getpid()))


def createLog(position):
    handler = RotatingFileHandler(
        f"{BASE_DIR}/log/invertor_{position}_log", backupCount=5)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S'))
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main():
    position = sys.argv[1]
    pidfile = f"/tmp/invertor_{position}.pid"

    createPid(pidfile)
    createLog(position)

    config = configparser.ConfigParser()
    config.read(f"{BASE_DIR}/conf/config.ini")

    monitor = Monitor(position, config)
    try:
        monitor.run()
    except Exception:
        logging.error("Exception occurred", exc_info=True)
    finally:
        if os.path.isfile(pidfile):
            os.unlink(pidfile)


if __name__ == "__main__":
    main()
