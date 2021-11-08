import utils
import http.client
import pickle
from config import conf
import sys, traceback
import json

class Checker:

    def __init__(self, logger):
        self.log = logger


    def check(self):
        db = conf.db.conn

        self.__heatingCounter = utils.toInt(db.get("__heatingCounter")) + 1
        db.set("__heatingCounter", self.__heatingCounter)

        self.checkTemperature()


    def checkTemperature(self):
        db = conf.db.conn

        data = dict()

        result = list()
        sensors = list()
        for item in db.keys("temp_sensor_*"):
            item = utils.toStr(item)

            #self.log.info("Item <%s>" % (item))
            sensor = pickle.loads(db.get(item))
            data[item] = sensor

            roomId = conf.HeatingSensors.items[sensor["sensorId"]]
            room = pickle.loads(db.get("heating_" + roomId))
            reqTemperature = room.get("temperature")

            # if a single room temperature - hysteresis is lower
            # than requested temperature call set on
            if self.__heatingCounter > conf.Daemon.Interval:
                if sensor['temperature'] < reqTemperature - conf.Heating.hysteresis:
                    self.log.info(
                        "Sensor: [%s] %.1fC < %.1fC" % (
                            sensor.get("sensorId"),
                            sensor.get("temperature"), reqTemperature))
                    result.append(1)
                else:
                    self.log.info(
                        "Sensor: [%s] %.1fC >= %.1fC" % (
                            sensor.get("sensorId"),
                            sensor.get("temperature"), reqTemperature))
                    result.append(0)

                sensors.append(int(sensor.get("sensorId")))

        """
        This method reduce requests to the switch hardware to one per x second
        Because permanently check of all actions is every 1s
        Persistent counter is saved into the db.
        """
        if self.__heatingCounter > conf.Daemon.Interval:
            # first delete heting counter
            db.set("__heatingCounter", 0)
            self.changeManifoldStatus(result, sensors)
            if sum(result) > 0:
                self.changeHeatingState(1)
            else:
                self.changeHeatingState(0)


    def changeManifoldStatus(self, result, sensors):
        req = [0] * 9
        pos = 0

        for sensor in sensors:
            for p in conf.HeatingSensors.mapSensorsToManifold.get(sensor):
                req[p] = result[pos]
            pos += 1

        req = "".join(map(str, req))
        self.log.info("Changing manifold at <%s> to: %s" % (
                      conf.HeatingSensors.manifoldIp, req))
        self.sendReq(conf.HeatingSensors.manifoldIp, "/" + req)


    def changeHeatingState(self, value):
        db = conf.db.conn

         # read actual value
        oldValue = utils.toInt(db.get("heating_state"))
        db.set("heating_state", value)
        newValue = utils.toInt(db.get("heating_state"))

        req = "/?p=%s&v=%s" % (conf.Heating.port, newValue)
        self.sendReq(conf.Heating.hwIp, req)


    def sendReq(self, ip, req):

        if (conf.Lights.httpConn == 1):

            conn = http.client.HTTPConnection(ip, timeout = 5)
            conn.request("GET", req)
            res  = conn.getresponse()
            conn.close()
            self.log.info("Request to: http://%s%s <%s %s>" % (
                ip, req, res.status, res.reason))
