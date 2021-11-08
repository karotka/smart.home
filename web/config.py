"""
"""
import configparser
import redis
import logging
import logging.handlers
from pythonjsonlogger import jsonlogger


def setWebLogger(config):
    logger = logging.getLogger('web')
    logger.setLevel(logging.INFO)

    logHandler = logging.handlers.TimedRotatingFileHandler(
         config.Web.LogFile, when="midnight")
    formatter = logging.Formatter(
         '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)



def setSensorLogger(config):
    logger = logging.getLogger("sensor")
    logger.setLevel(logging.INFO)

    logHandler = logging.handlers.TimedRotatingFileHandler(
         "log/sensor_log", when="midnight")
    formatter = jsonlogger.JsonFormatter()
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)


class Config():

    def __init__(self):
        config = configparser.ConfigParser()
        #config.read("/root/project/conf/config.ini")
        config.read("conf/config.ini")

        self.parse(config)

        self.Default = self.Default(config)
        self.Daemon = self.Daemon(config)
        self.db = self.Db(config)
        self.Web = self.Web(config)
        self.HeatingSensors = self.HeatingSensors(config)
        self.Lights = self.Lights(config)
        self.Heating = self.Heating(config)

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


    class HeatingSensors:

        def __init__(self, config):
            sensors = list(map(str.strip, config["HeatingSensors"]["sensorIds"].split(",")))
            rooms = list(map(str.strip, config["HeatingSensors"]["roomIds"].split(",")))
            exec("self.mapSensorsToManifold=%s" % config["HeatingSensors"]["mapSensorsToManifold"])
            self.manifoldIp = config["HeatingSensors"]["manifoldIp"]
            self.items = dict(zip(sensors, rooms))


    class Lights:
        def __init__(self, config):
            self.names = list(map(str.strip, config["Lights"]["lightNames"].split(",")))
            self.ids = list(map(str.strip, config["Lights"]["lightIds"].split(",")))
            self.hwIp = config["Lights"]["hwIp"]
            self.httpConn = int(config["Lights"]["httpConn"])

            self.ports = list(
                map(int,
                    map(str.strip, config["Lights"]["ports"].split(","))
                )
            )



conf = Config()
