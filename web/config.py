"""
"""
import configparser
import os
import redis
import logging
import logging.handlers
import json
import http.client
from pythonjsonlogger import jsonlogger
from influxdb import InfluxDBClient
from influxdb import DataFrameClient



def setWebLogger(config):
    logger = logging.getLogger('web')
    logger.setLevel(logging.INFO)

    logHandler = logging.handlers.TimedRotatingFileHandler(
         config.Web.LogFile, when="midnight", backupCount = 3)
    formatter = logging.Formatter(
         '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)

log = logging.getLogger('web')


def setSensorLogger(config):
    logger = logging.getLogger("sensor")
    logger.setLevel(logging.INFO)

    logHandler = logging.handlers.TimedRotatingFileHandler(
         "log/sensor_log", when="midnight", backupCount = 99)
    formatter = jsonlogger.JsonFormatter()
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)


def sendReq(ip, req):

    conn = http.client.HTTPConnection(ip, timeout = 5)
    conn.request("GET", req)
    res  = conn.getresponse()
    data = res.read()
    conn.close()
    log.info("Request to: http://%s%s <%s %s> %s" % (
            ip, req, res.status, res.reason, data))
    return data


class Config():

    def __init__(self):
        config = configparser.ConfigParser()
        #config.read("/root/project/conf/config.ini")
        config.read("conf/config.ini")

        self.parse(config)

        self.Default = self.Default(config)
        self.Daemon = self.Daemon(config)
        self.db = self.Db(config)
        self.Mqtt = self.Mqtt(config)
        self.Influx = self.Influx(config)
        self.Web = self.Web(config)
        self.HeatingSensors = self.HeatingSensors(config)
        self.Lights = self.Lights(config)
        self.Heating = self.Heating(config)
        self.Blinds = self.Blinds(config)
        self.Tuya = self.Tuya(config)
        self.Battery = self.Battery(config)

        setWebLogger(self)
        setSensorLogger(self)
        


    def parse(self, config):
        for item in config.sections():
            if not hasattr(self, item):
                t = type(item, (object, ), {})()
                for key in config[item]:
                    setattr(t, key, config[item][key])

                setattr(self, item, t)

    class Default:

        def __init__(self, config):
            pass


    class Tuya:
        """Lazily reloads snapshot.json whenever its mtime changes.

        DHCP can renumber Tuya devices mid-flight (the unit has no
        static-IP option in the app), so the conf can't be a one-shot
        load — every consumer that reads .devices needs the current
        IP. We watch the snapshot file's mtime and rebuild the dict
        when the rediscover job updates it. Cheap: one stat() per
        access, only re-parses when the file actually changed.
        """
        _SNAPSHOT_PATH = "conf/snapshot.json"

        def __init__(self, config):
            self.hpStatus = {}
            self._snap_mtime = 0
            self._devices = {}
            self._reload()

            tuyaConf = "tinytuya.json"
            with open(tuyaConf, 'r') as tuyaConf:
                self.auth = json.load(tuyaConf)

        def _reload(self):
            try:
                m = os.path.getmtime(self._SNAPSHOT_PATH)
            except OSError:
                return
            if m == self._snap_mtime and self._devices:
                return
            with open(self._SNAPSHOT_PATH) as f:
                data = json.load(f)
            self._devices = {item["id"]: item for item in data["devices"]}
            self._snap_mtime = m

        @property
        def devices(self):
            self._reload()
            return self._devices

    class Daemon:

        def __init__(self, config):
            self.Pid = config["Daemon"].get("Pid")
            self.Interval = int(config["Daemon"].get("Interval"))
            self.LogFile = config["Daemon"].get("LogFile")


    class Db:

        def __init__(self, config):
            host = config["Db"].get("host")
            port = int(config["Db"].get("port"))
            self.conn = redis.Redis(host, port)


    class Mqtt:

        def __init__(self, config):
            self.host = config["Mqtt"].get("host", "127.0.0.1")
            self.port = int(config["Mqtt"].get("port", "1883"))


    class Battery:
        """LiPo pack endpoints used to derive a load-compensated SOC.

        voltage_empty / voltage_full define the linear voltage-to-SOC
        map; internal_ohm is the pack's effective series resistance used
        to back out the open-circuit voltage from the terminal reading
        under load (V_open = V_terminal + net_discharge_current * R).
        """
        def __init__(self, config):
            sect = config["Battery"]
            self.voltage_empty = float(sect.get("voltage_empty", "47.0"))
            self.voltage_full  = float(sect.get("voltage_full",  "57.7"))
            self.internal_ohm  = float(sect.get("internal_ohm",  "0.015"))


    class Influx:

        def __init__(self, config):
            self.host = config["Influx"].get("host")
            self.port = int(config["Influx"].get("port"))
            self.db   = config["Influx"].get("db")
            self.hpDb = config["Influx"].get("hpDb")

        def getClient(self):
            return InfluxDBClient(host = self.host, port = self.port, database = self.db)

        def getDfClient(self):
            return DataFrameClient(host = self.host, port = self.port, database = self.db)
        
        def getHpClient(self):
            return InfluxDBClient(host = self.host, port = self.port, database = self.hpDb)


    class Web:

        def __init__(self, config):
            self.Host = config["Web"].get("Host")
            self.Port = int(config["Web"].get("Port"))
            self.LogFile = config["Web"].get("LogFile")


    class Heating:

        def __init__(self, config):
            self.minimalTemperature = float(config["Heating"]["minimalTemperature"])
            self.maximalTemperature = float(config["Heating"]["maximalTemperature"])
            self.hysteresis = float(config["Heating"]["hysteresis"])
            self.hwIp = config["Heating"]["hwIp"]
            self.port = int(config["Heating"]["port"])

            names = list(map(str.strip, config["Heating"]["roomNames"].split(',')))
            # roomIds live once in [HeatingSensors] so renaming a room
            # is a one-line edit instead of risking a drift across two
            # sections.
            roomIds = list(map(str.strip, config["HeatingSensors"]["roomIds"].split(',')))
            assert len(names) == len(roomIds), (
                "Heating.roomNames (%d) must match HeatingSensors.roomIds (%d)"
                % (len(names), len(roomIds)))

            self.items = dict(zip(roomIds, names))


    class Blinds:
        """One [Blinds] entry per Tuya cover device.

        items = {
            "<short_id>": {
                "id":   "bfXXXXXXXXX",       # Tuya device id
                "name": "Roleta xyz",         # human label
                "ip":   "192.168.X.Y",        # local IP (informational; auto-discovered)
                "key":  "<local_key>",
                "ver":  "3.3",
                "room": "<room name>"
            },
            ...
        }
        """

        def __init__(self, config):
            raw = config["Blinds"].get("items", "{}")
            exec("self.items = %s" % raw)


    class HeatingSensors:

        def __init__(self, config):
            sensors = list(map(int, config["HeatingSensors"]["sensorIds"].split(",")))
            rooms = list(map(str.strip, config["HeatingSensors"]["roomIds"].split(",")))
            exec("self.mapSensorsToManifold=%s" % config["HeatingSensors"]["mapSensorsToManifold"])
            self.manifoldIp = config["HeatingSensors"]["manifoldIp"]
            self.items = dict(zip(sensors, rooms))
            self.names = dict(zip(rooms, sensors))
            # Rooms whose sensor is "informational only" — temperature
            # shows up on the dashboard but doesn't feed the TC on/off
            # decision and the UI suppresses setpoint controls. Comma-
            # separated roomIds in [HeatingSensors].external.
            self.external = set(
                r.strip() for r in
                config["HeatingSensors"].get("external", "").split(",")
                if r.strip())


    class Lights:

        def __init__(self, config):
            self.httpConn = int(config["Lights"]["httpConn"])
            exec("self.items=%s" % config["Lights"]["items"])


        def status(self, ip, port):
            if (self.httpConn == 1):
                url = "/?p=%s" % port
                data = sendReq(ip, url)
                data = json.loads(data)
                return data.get("v")


conf = Config()
