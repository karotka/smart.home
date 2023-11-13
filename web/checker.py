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
        self.checkLight()


    def checkLight(self):
        db = conf.db.conn
        tm = time.strftime("%H", time.localtime())
        tm  = utils.toInt(tm)

        if tm > 6 and tm <= 16:
            newValue = "0"
        else:
            newValue = "1"
        req = "/?p=%s&v=%s" % (1, newValue)

        oldValue = utils.toStr(db.get("light_night_state"))
        
        #self.log.info("tm: %s %s - >  %s" %(tm, oldValue, newValue))
        if oldValue != newValue:
            data = self.sendReq(conf.Heating.hwIp, req)
            data = json.loads(data)
            newValue = data.get("v")
            db.set("light_night_state", newValue)
            self.log.info("Set night light to: %s" % newValue)


    def checkTemperature(self):

        """
        Templ
        """
        db = conf.db.conn
        now  =  time.localtime()


        data = dict()
        result = list()
        sensors = list()
        for item in db.keys("temp_sensor_*"):
            item = utils.toStr(item)

            try:
                #self.log.info("Item <%s>" % (item))
                sensor = pickle.loads(db.get(item))
                data[item] = sensor
                roomId = conf.HeatingSensors.items[sensor["sensorId"]]
                room = pickle.loads(db.get("heating_" + roomId))
                reqTemperature = room.get("temperature")
            except Exception as e:
                #self.log.error(e, exc_info=True)
                continue

            # if a single room temperature - hysteresis is lower
            # than requested temperature call set on
            if self.__heatingCounter > conf.Daemon.Interval:
                if sensor['temperature'] > reqTemperature:
                    self.log.debug(
                        "Sensor: [%s] %.2fC > %.2fC = OK" % (
                            sensor.get("sensorId"),
                            sensor.get("temperature"), reqTemperature))
                    result.append(0)
                else:
                    self.log.info(
                        "Sensor: [%s] %.2fC < %.2fC = LOW" % (
                            sensor.get("sensorId"),
                            sensor.get("temperature"), reqTemperature))
                    result.append(1)
                sensors.append(int(sensor.get("sensorId")))

                #self.log.info("Sensors: %s" % sensors)
                #self.log.info("result: %s" % result)
        """
        This if reduce requests to the switch hardware to one per x second
        Because permanently check of all actions is every 1s
        Persistent counter is saved into the db.
        """
        if self.__heatingCounter > conf.Daemon.Interval:

            # first delete heting counter
            db.set("__heatingCounter", 0)
          
            # heatting is OFF
            if now.tm_hour > 22 or now.tm_hour < 5:
                self.changeManifoldStatus([0 for _ in range(len(result))], sensors)
                self.changeHeatingState(0)
                self.log.info("Heating is OFF bettwen 23 and 4 hour: <%s>" % now.tm_hour)
                return
            
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
            portList = conf.HeatingSensors.mapSensorsToManifold.get(sensor)

            for p in portList:
                #self.log.info("sensor: %s port: %s" % (sensor, p))
                if result[pos] != 0:
                    newValue |= 1 << p
            pos += 1

        # format binnary to string, cut 0b and reverse
        newValue = format(newValue, '#011b')[2:][::-1]
        oldValue = utils.toStr(db.get("heating_manifold_state"))
        #self.log.info("new: %s old: %s" % (newValue, oldValue))

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
        month = ("%s-%02d") % (time.localtime().tm_year, time.localtime().tm_mon)

        # read actual value
        oldValue = utils.toInt(db.get("heating_state"))

        if oldValue != value:
            req = "/?p=%s&v=%s" % (conf.Heating.port, value)
            data = self.sendReq(conf.Heating.hwIp, req)
            data = json.loads(data)

            newValue = int(data.get("v"))
            db.set("heating_state", newValue)

#<<<<<<< HEAD
#        if oldValue == 0 and value == 1:
#            db.set("heating_time", 0)
#
#        if value == 1:
#            db.incrby("heating_time", conf.Daemon.Interval)
#            #newValue = utils.toInt(db.get("heating_state"))
#=======
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
#>>>>>>> 707ba65e7ccfb0ff49afb9ae498388c08196dd7d


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
