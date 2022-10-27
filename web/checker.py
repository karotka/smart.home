import utils
import http.client
import sys, traceback
import json
import time
import pickle
from config import conf

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
                if sensor['temperature'] > reqTemperature + conf.Heating.hysteresis:
                    self.log.debug(
                        "Sensor: [%s] %.2fC > %.2fC = OK" % (
                            sensor.get("sensorId"),
                            sensor.get("temperature"), reqTemperature + conf.Heating.hysteresis))
                    result.append(0)
                else:
                    self.log.info(
                        "Sensor: [%s] %.2fC < %.2fC = LOW" % (
                            sensor.get("sensorId"),
                            sensor.get("temperature"), reqTemperature + conf.Heating.hysteresis))
                    result.append(1)
                sensors.append(int(sensor.get("sensorId")))

        """
        This if reduce requests to the switch hardware to one per x second
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
        db = conf.db.conn

        newValue = 0b0
        pos = 0
        for sensor in sensors:
            for p in conf.HeatingSensors.mapSensorsToManifold.get(sensor):
                if result[pos] != 0:
                    newValue |= 1 << p
            pos += 1

        # format binnary to string, cut 0b and reverse
        newValue = format(newValue, '#011b')[2:][::-1]
        oldValue = utils.toStr(db.get("heating_manifold_state"))

        if oldValue != newValue:
            self.log.info("Changing manifold at <%s> to: %s" % (
                      conf.HeatingSensors.manifoldIp, newValue))
            data = self.sendReq(conf.HeatingSensors.manifoldIp, "/" + newValue)
            data = json.loads(data)
            newValue = data.get("v")
            db.set("heating_manifold_state", newValue)
        else:
            self.log.debug("Manifold at <%s> is still: %s" % (
                      conf.HeatingSensors.manifoldIp, newValue))


    def changeHeatingState(self, value):
        db = conf.db.conn
        month = ("%s-%s") % (time.localtime().tm_year, time.localtime().tm_mon)

        # read actual value
        oldValue = utils.toInt(db.get("heating_state"))

        if oldValue != value:
            req = "/?p=%s&v=%s" % (conf.Heating.port, value)
            data = self.sendReq(conf.Heating.hwIp, req)
            data = json.loads(data)

            newValue = int(data.get("v"))
            db.set("heating_state", newValue)

<<<<<<< HEAD
        if oldValue == 0 and value == 1:
            db.set("heating_time", 0)

        if value == 1:
            db.incrby("heating_time", conf.Daemon.Interval)
            #newValue = utils.toInt(db.get("heating_state"))
=======
            tm = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            data = db.get("heating_time_%s" % month)
            if not data:
                data = list()
            else:
                data = pickle.loads(data)
            if oldValue == 0 and value == 1:
                data.append({
                    "date" : tm,
                    "status" : True
                })
            else:
                data.append({
                    "date" : tm,
                    "status" : False
                })
            
            db.set("heating_time_%s" % month, pickle.dumps(data))
>>>>>>> 707ba65e7ccfb0ff49afb9ae498388c08196dd7d


    def sendReq(self, ip, req):

        if (conf.Lights.httpConn == 1):

            conn = http.client.HTTPConnection(ip, timeout = 5)
            conn.request("GET", req)
            res  = conn.getresponse()
            data = res.read()
            conn.close()
            self.log.info("Request to: http://%s%s <%s %s>" % (
                ip, req, res.status, res.reason))
            return data
