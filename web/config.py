"""
"""
import configparser
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
        self.Influx = self.Influx(config)
        self.Web = self.Web(config)
        self.HeatingSensors = self.HeatingSensors(config)
        self.Lights = self.Lights(config)
        self.Heating = self.Heating(config)
        self.Blinds = self.Blinds(config)
        self.Tuya = self.Tuya(config)

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

        def __init__(self, config):
            f = open("conf/snapshot.json")
            data = json.load(f)
            self.devices = dict()
            for item in data["devices"]:
                self.devices[item["id"]] = item


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


    class Influx:

        def __init__(self, config):
            self.host = config["Influx"].get("host")
            self.port = int(config["Influx"].get("port"))
            self.db = config["Influx"].get("db")

        def getClient(self):
            return InfluxDBClient(host = self.host, port = self.port, database = self.db)

        def getDfClient(self):
            return DataFrameClient(host = self.host, port = self.port, database = self.db)


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
            roomIds = list(map(str.strip, config["Heating"]["roomIds"].split(',')))

            self.items = dict()
            for i in range(0, len(names)):
                self.items[roomIds[i]] = names[i]


    class Blinds:

        def __init__(self, config):
            exec("self.ports=%s" % config["Blinds"]["ports"])
            names = list(map(str.strip, config["Blinds"]["names"].split(',')))
            ids = list(map(str.strip, config["Blinds"]["ids"].split(',')))
            
            self.times =  list(map(int, config["Blinds"]["times"].split(',')))
            self.items = dict()
            for i in range(0, len(names)):
                self.items[ids[i]] = names[i]


    class HeatingSensors:

        def __init__(self, config):
            sensors = list(map(int, config["HeatingSensors"]["sensorIds"].split(",")))
            rooms = list(map(str.strip, config["HeatingSensors"]["roomIds"].split(",")))
            exec("self.mapSensorsToManifold=%s" % config["HeatingSensors"]["mapSensorsToManifold"])
            self.manifoldIp = config["HeatingSensors"]["manifoldIp"]
            self.items = dict(zip(sensors, rooms))
            self.names = dict(zip(rooms, sensors))


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
