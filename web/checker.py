import utils
import http.client
import pickle
from config import conf
import sys, traceback
import json

class Checker:

    def __init__(self, logger):
        self.logger = logger

    def check(self):

        try:
            db = conf.db.conn

            self.__heatingCounter = utils.toInt(db.get("__heatingCounter")) + 1
            db.set("__heatingCounter", self.__heatingCounter)

            self.checkTemperature()
        except Exception as e:
            self.logger.error(sys.exc_info())


    def checkTemperature(self):
        db = conf.db.conn

        data = dict()

        needOff = True
        for item in db.keys("temp_sensor_*"):
            sensor = pickle.loads(db.get(item))
            data[utils.toStr(item)] = sensor

            roomId = "heating_" + conf.HeatingSensors.items[sensor["sensorId"]]
            reqTemperature = utils.toFloat(db.get(roomId))

            # if a single room temperature - hysteresis is lower
            # than requested temperature call set on
            if sensor['temperature'] - conf.Heating.hysteresis < reqTemperature:
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
            db.set("__heatingCounter", 0)

            state = self.getHeatingState()

            if state != value:

                #http.client .....
                self.logger.info("changing state to: --> %s" % value)
                db.set("heating_state", value)


    def getHeatingState(self):
        ip   = conf.Heating.hwIp
        port = conf.Heating.port

        if (conf.Lights.httpConn == 1):
            resData = self.sendReq(conf.Lights.hwIp, "/")
        else:
            resData = {
                "temp" : 49.46,
                "states": []
            }
            resData["states"].append({"id" : 0, "value":0})
            resData["states"].append({"id" : 1, "value":0})
            resData["states"].append({"id" : 2, "value":0})
            resData["states"].append({"id" : 3, "value":0})
            resData["states"].append({"id" : 4, "value":1})

            #conf.Log.log.info("GET http://%s/ -> %s" % (
            #    ip, resData))

        value = 0
        for item in resData["states"]:
            if item["id"] == port:
                value = item["value"]
                break
        return value


    def sendReq(self, ip, req):
        conn = http.client.HTTPConnection(ip)
        conn.request("GET", req)
        response = conn.getresponse()

        data = None
        if response == 200:
            data = json.loads(response.read())
        return data
