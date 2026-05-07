import utils
import http.client
import sys, traceback
import json
import time
import pickle
from config import conf

# Solar-surplus boost: thresholds and constants
SOLAR_BOOST_SOC_MIN     = 70      # battery state of charge [%] required before we boost
SOLAR_BOOST_MARGIN_W    = 200     # solar must beat HP draw by at least this many W
SOLAR_BOOST_TARGET_TEMP = 50      # heating target [°C] while we're dumping surplus into water
SOLAR_BOOST_INTERVAL    = 600     # 10 minutes between checks
HP_POWER_DEVICE_ID      = "bf2f6c60f5d1b15d9c6urw"   # TČ switch (kWh meter on the TC line)


class Checker:

    def __init__(self, logger):
        self.log = logger


    def check(self):
        db = conf.db.conn

        self.__heatingCounter = utils.toInt(db.get("__heatingCounter")) + 1
        db.set("__heatingCounter", self.__heatingCounter)

        self.checkTemperature()
        self.checkLight()
        self.checkSolarBoost()


    def checkLight(self):
        db = conf.db.conn
        tm = time.strftime("%H", time.localtime())
        tm  = utils.toInt(tm)

        #if tm >= 6 and tm <= 16:
        if tm >= 8 and tm <= 15:
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

        heatingDirection = utils.toStr(db.get("heating_direction"))

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
            if heatingDirection == "heating":
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
            else:
                if self.__heatingCounter > conf.Daemon.Interval:
                    if sensor['temperature'] < reqTemperature:
                        self.log.debug(
                            "Sensor: [%s] %.2fC < %.2fC = OK" % (
                                sensor.get("sensorId"),
                                sensor.get("temperature"), reqTemperature))
                        result.append(0)
                    else:
                        self.log.info(
                            "Sensor: [%s] %.2fC > %.2fC = LOW" % (
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
            # 6 - nedele
            #if now.tm_wday in (0,1,2,3,4,5):
            #    if now.tm_hour > 23 or now.tm_hour < 2:
            #        self.changeManifoldStatus([0 for _ in range(len(result))], sensors)
            #        self.changeHeatingState(0)
            #        self.log.info("Heating is OFF bettwen 23 and 4 hour: <%s> day: %s" % (now.tm_hour, now.tm_wday))
            #        return
            #else:
            #    if now.tm_hour > 23 or now.tm_hour < 3:
            #        self.changeManifoldStatus([0 for _ in range(len(result))], sensors)
            #        self.changeHeatingState(0)
            #        self.log.info(
            #                "Heating is OFF bettwen 23 and <%s> hour, for day: %s" % (
            #                    now.tm_hour, now.tm_wday))
            #        return
            
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


    # -------------------------------------------------------------------
    # Solar surplus -> heating water boost
    #
    # Once every SOLAR_BOOST_INTERVAL seconds: if the battery is at least
    # SOLAR_BOOST_SOC_MIN percent and the solar arrays are producing more
    # power than the heat pump is currently drawing (with a margin), bump
    # the heating target water temperature up to SOLAR_BOOST_TARGET_TEMP.
    # When the surplus disappears we restore whatever the target was
    # before we touched it (saved in redis at solar_boost_prev_target).
    # -------------------------------------------------------------------

    def checkSolarBoost(self):
        db = conf.db.conn
        now_ts = int(time.time())
        last_run = utils.toInt(db.get("solar_boost_last_run"))
        if now_ts - last_run < SOLAR_BOOST_INTERVAL:
            return
        db.set("solar_boost_last_run", now_ts)

        soc = self.__batterySoc()
        solar_w = self.__solarPower()
        hp_w = self.__hpPower()

        if soc is None:
            self.log.debug("solar boost: invertor data not available")
            return

        active = utils.toInt(db.get("solar_boost_active"))
        surplus = (soc >= SOLAR_BOOST_SOC_MIN
                   and solar_w is not None and hp_w is not None
                   and solar_w - hp_w >= SOLAR_BOOST_MARGIN_W)

        self.log.info(
            "Solar boost: SOC=%.0f%% solar=%.0fW HP=%.0fW surplus=%s active=%s" % (
                soc, solar_w or 0, hp_w or 0, surplus, bool(active)))

        if surplus and not active:
            prev = self.__heatingTarget()
            if prev is None:
                self.log.warning("solar boost: cannot read current heating target")
                return
            if prev == SOLAR_BOOST_TARGET_TEMP:
                # already there; just record the active flag
                db.set("solar_boost_active", 1)
                return
            db.set("solar_boost_prev_target", prev)
            if self.__setHeatingTarget(SOLAR_BOOST_TARGET_TEMP):
                db.set("solar_boost_active", 1)
                self.log.info("solar boost ENGAGED: heating target %s -> %s °C" %
                              (prev, SOLAR_BOOST_TARGET_TEMP))

        elif not surplus and active:
            prev = utils.toInt(db.get("solar_boost_prev_target")) or 35
            if self.__setHeatingTarget(prev):
                db.set("solar_boost_active", 0)
                self.log.info("solar boost RELEASED: heating target -> %s °C" % prev)


    # ---- solar-boost helpers -----------------------------------------

    def __batterySoc(self):
        """Average state of charge across both invertors, or None."""
        db = conf.db.conn
        try:
            i1 = pickle.loads(db.get("invertor_1"))
            i2 = pickle.loads(db.get("invertor_2"))
        except Exception:
            return None
        socs = [i1.get("batteryCapacity"), i2.get("batteryCapacity")]
        socs = [float(s) for s in socs if s is not None]
        if not socs:
            return None
        return sum(socs) / len(socs)


    def __solarPower(self):
        """Total solar input power (W) summed across both invertors,
        or None if no data."""
        db = conf.db.conn
        try:
            i1 = pickle.loads(db.get("invertor_1"))
            i2 = pickle.loads(db.get("invertor_2"))
        except Exception:
            return None
        return (float(i1.get("solarCurrent", 0)) * float(i1.get("solarVoltage", 0))
                + float(i2.get("solarCurrent", 0)) * float(i2.get("solarVoltage", 0)))


    def __hpPower(self):
        """Read live HP power consumption (W) from the Tuya wattmeter
        sitting on the heat-pump line. Returns None on failure."""
        try:
            import tinytuya
        except ImportError:
            return None
        dev = conf.Tuya.devices.get(HP_POWER_DEVICE_ID)
        if not dev:
            return None
        try:
            d = tinytuya.OutletDevice(
                dev_id=dev["id"], address=dev["ip"],
                local_key=dev.get("key"), version=dev.get("ver", "3.4"))
            d.set_socketTimeout(2)
            res = d.status()
            dps = res.get("dps") if isinstance(res, dict) else None
            if not dps:
                return None
            # DPS 19 is total active power, scaled by 0.1 -> W
            raw = dps.get("19")
            return float(raw) / 10.0 if raw is not None else None
        except Exception as e:
            self.log.warning("hp wattmeter read failed: %s" % e)
            return None


    def __heatingTarget(self):
        """Current heating target temp (PG1[4]) in °C, or None."""
        ints = self.__pgRead(1)
        return ints[4] if ints else None


    def __setHeatingTarget(self, value):
        """Mutate PG1[4] and push it to the heat pump. Returns True on success."""
        ints = self.__pgRead(1)
        if ints is None:
            return False
        if ints[4] == value:
            return True
        ints[4] = int(value)
        return self.__pgWrite(1, ints)


    def __pgRead(self, group_idx):
        """Pull parameter_group_<group_idx> through the Tuya cloud and
        return its 20 int32 values, or None."""
        import base64, struct
        try:
            import tinytuya
        except ImportError:
            return None
        try:
            auth = conf.Tuya.auth
            api = tinytuya.Cloud(
                apiRegion=auth.get("apiRegion", "eu"),
                apiKey=auth["apiKey"],
                apiSecret=auth["apiSecret"],
            )
            res = api.getstatus("bf06f140ee20807fdaalyq")
            if not isinstance(res, dict) or not res.get("success"):
                self.log.warning("pg read: cloud refused: %s" % res)
                return None
            code = "parameter_group_%d" % group_idx
            b64 = next((it["value"] for it in res.get("result", [])
                        if isinstance(it, dict) and it.get("code") == code), None)
            if not b64:
                return None
            return list(struct.unpack(">20i", base64.b64decode(b64)))
        except Exception as e:
            self.log.warning("pg read failed: %s" % e)
            return None


    def __pgWrite(self, group_idx, ints):
        """Push 20 int32 values back to the heat pump via the local Tuya
        tunnel (DPS 117 + group_idx)."""
        import base64, struct
        try:
            import tinytuya
        except ImportError:
            return False
        try:
            dev = conf.Tuya.devices.get("bf06f140ee20807fdaalyq")
            d = tinytuya.OutletDevice(
                dev_id=dev["id"], address=dev["ip"],
                version=dev.get("ver", "3.3"))
            d.set_socketTimeout(2)
            b64 = base64.b64encode(struct.pack(">20i", *ints)).decode()
            d.set_value(117 + group_idx, b64)
            return True
        except Exception as e:
            self.log.error("pg write failed: %s" % e, exc_info=True)
            return False
