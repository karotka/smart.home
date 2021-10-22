"""
"""
import configparser
import redis
import logging
from pythonjsonlogger import jsonlogger

class Config():

    def __init__(self):
        config = configparser.ConfigParser()
        config.read("/root/project/conf/config.ini")

        self.parse(config)

        self.Default = self.Default(config)
        self.db = self.Db(config)
        self.HeatingSensors = self.HeatingSensors(config)
        self.Lights = self.Lights(config)
        self.Log = self.Log(config)
        self.SensorLog = self.SensorLog(config)

        self.Heating = self.Heating(config)


    def parse(self, config):
        for item in config.sections():
            if not hasattr(self, item):
                t = type(item, (object, ), {})()
                for key in config[item]:
                    setattr(t, key, config[item][key])

                setattr(self, item, t)

    class Default:

        def __init__(self, config):
            self.DaemonPid = config["Default"].get("DaemonPid")

    class SensorLog:

        def __init__(self, config):
             logger = logging.getLogger()
             logHandler = logging.FileHandler("log/sensor_log")
             logHandler.setLevel(logging.INFO)
             formatter = jsonlogger.JsonFormatter()
             logHandler.setFormatter(formatter)
             logger.addHandler(logHandler)
             self.log = logger

    class Log:

        def __init__(self, config):
            logger = logging.getLogger('web')
            fh = logging.FileHandler("log/smart.home_log")
            fh.setLevel(logging.INFO)

            formatstr = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            formatter = logging.Formatter(formatstr)

            fh.setFormatter(formatter)

            logger.addHandler(fh)

            self.log = logger

    class Db:

        def __init__(self, config):
            host = config["Db"].get("host")
            port = int(config["Db"].get("port"))
            self.conn = redis.Redis(host, port)


    class Heating:

        def __init__(self, config):
            self.minimalTemperature = float(config["Heating"]["minimalTemperature"])
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
