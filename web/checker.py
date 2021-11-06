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

        needOff = True
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
            if sensor['temperature'] < reqTemperature - conf.Heating.hysteresis:
                self.log.info(
                    "Sensor: [%s] %.1fC < %.1fC" % (
                        sensor.get("sensorId"),
                        sensor.get("temperature"), reqTemperature))
                needOff = False
                self.changeHeatingState(1)
                break

        if needOff == True:
            self.changeHeatingState(0)

    """
    This method reduce requests to the switch hardware to one per x second
    Because permanently check of all actions is every 1s
    Persistent counter is saved into the db.
    """
    def changeHeatingState(self, value):
        db = conf.db.conn

        if self.__heatingCounter > 10:
            # first delete heting counter
            db.set("__heatingCounter", 0)

            # read actual value
            oldValue = utils.toInt(db.get("heating_state"))
            db.set("heating_state", value)
            newValue = utils.toInt(db.get("heating_state"))

            if oldValue != newValue:
                req = "/?p=%s&v=%s" % (conf.Heating.port, newValue)
                resData = self.sendReq(conf.Lights.hwIp, req)


    def sendReq(self, ip, req):

        if (conf.Lights.httpConn == 1):
            ip = conf.Heating.hwIp

            conn = http.client.HTTPConnection(ip, timeout = 5)
            conn.request("GET", req)
            res  = conn.getresponse()
            conn.close()
            self.log.info("Changing state to: %s%s -> %s %s" % (
                ip, req, res.status, res.reason))
