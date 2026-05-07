import utils
import http.client
import sys, traceback
import json
import time
import pickle
from config import conf

# Solar-surplus boost: thresholds and constants
#
# We can't detect surplus by looking at solar output alone — once the
# battery is full the MPPT throttles back to whatever the load needs,
# so "produced power" tracks consumption and the apparent margin is
# always zero. Instead we use the battery itself as the headroom
# indicator: if SOC is high and the battery isn't being drained, then
# the panels HAVE headroom (they're just curtailed); turning on the
# heat pump will draw more and the panels will ramp up to feed it.
#
# Hysteresis: every cloud passing the array dips solar output for a
# minute or two. We don't release the boost on the first miss — the
# condition has to fail SOLAR_BOOST_RELEASE_MISSES times in a row
# (= ~30 min on the 10-min check cadence) before we restore the
# previous heating target.
SOLAR_BOOST_SOC_MIN          = 70      # battery state of charge [%] required to engage
SOLAR_BOOST_DISCHARGE_MAX_A  = 5       # battery discharge current [A] above this = no surplus
SOLAR_BOOST_DAYTIME_VOLT     = 100     # solarVoltage [V] threshold to call it daytime
SOLAR_BOOST_TARGET_TEMP      = 50      # heating target [°C] while parking surplus
SOLAR_BOOST_INTERVAL         = 600     # seconds between checks
SOLAR_BOOST_RELEASE_MISSES   = 3       # consecutive failed checks before releasing
HP_POWER_DEVICE_ID           = "bf2f6c60f5d1b15d9c6urw"   # kWh meter on the TC line (informational logging)

# Terasa nightly drift correction: once after 23:00, if Roleta terasa
# isn't sitting at its expected partial position, fully close it and
# then re-target so the calibration stays consistent.
TERASA_CAL_HOUR              = 23      # check fires only after this hour
TERASA_CAL_OK_MIN            = 17
TERASA_CAL_OK_MAX            = 20
TERASA_CAL_TARGET_PCT        = 18
TERASA_CAL_PAUSE_SEC         = 5


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
        self.checkTerasaCalibration()


    # Night light is ON whenever the PV panels stop producing voltage —
    # essentially "PV says it's dark". The threshold needs to be safely
    # above the inverter's idle / noise reading but low enough to flip
    # at the very first hint of dawn light; 24 V matches the user's
    # observed behaviour.
    NIGHT_LIGHT_PV_VOLT = 24

    def checkLight(self):
        db = conf.db.conn

        solar_v = self.__solarVoltage()
        if solar_v is not None:
            newValue = "0" if solar_v >= self.NIGHT_LIGHT_PV_VOLT else "1"
        else:
            tm = utils.toInt(time.strftime("%H", time.localtime()))
            newValue = "0" if 8 <= tm <= 15 else "1"

        req = "/?p=%s&v=%s" % (1, newValue)
        oldValue = utils.toStr(db.get("light_night_state"))

        if oldValue != newValue:
            data = self.sendReq(conf.Heating.hwIp, req)
            data = json.loads(data)
            newValue = data.get("v")
            db.set("light_night_state", newValue)
            self.log.info(
                "Set night light to: %s (solarV=%s)" %
                (newValue, "%.0fV" % solar_v if solar_v is not None else "n/a"))


    def __solarVoltage(self):
        """Highest solar string voltage [V] across both invertors,
        or None if invertor data isn't in redis yet."""
        db = conf.db.conn
        try:
            i1 = pickle.loads(db.get("invertor_1"))
            i2 = pickle.loads(db.get("invertor_2"))
        except Exception:
            return None
        return max(float(i1.get("solarVoltage", 0)),
                   float(i2.get("solarVoltage", 0)))


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

        try:
            i1 = pickle.loads(db.get("invertor_1"))
            i2 = pickle.loads(db.get("invertor_2"))
        except Exception:
            self.log.debug("solar boost: invertor data not available")
            return

        # --- read all three signals at once ---
        socs = [float(d.get("batteryCapacity", 0)) for d in (i1, i2)]
        soc = sum(socs) / len(socs)

        # battery is being drained when ANY invertor's discharge current
        # exceeds the threshold (loads bigger than solar can cover)
        discharge_a = max(float(i1.get("batteryDischargeCurrent", 0)),
                          float(i2.get("batteryDischargeCurrent", 0)))

        # solar voltage > threshold on either string indicates daytime;
        # the actual produced wattage is unreliable as a surplus signal
        # because the MPPT throttles to match load when battery is full.
        solar_v = max(float(i1.get("solarVoltage", 0)),
                      float(i2.get("solarVoltage", 0)))

        # informational only — logged but not used for the decision
        solar_w = self.__solarPower() or 0
        hp_w = self.__hpPower()

        surplus = (
            soc >= SOLAR_BOOST_SOC_MIN
            and discharge_a <= SOLAR_BOOST_DISCHARGE_MAX_A
            and solar_v >= SOLAR_BOOST_DAYTIME_VOLT
        )

        active = utils.toInt(db.get("solar_boost_active"))
        misses = utils.toInt(db.get("solar_boost_misses"))

        self.log.info(
            "Solar boost: SOC=%.0f%% disch=%.1fA solarV=%.0fV solar=%.0fW HP=%s surplus=%s active=%s misses=%d" % (
                soc, discharge_a, solar_v, solar_w,
                ("%.0fW" % hp_w if hp_w is not None else "?"),
                surplus, bool(active), misses))

        if surplus:
            db.set("solar_boost_misses", 0)
            if not active:
                prev = self.__heatingTarget()
                if prev is None:
                    self.log.warning("solar boost: cannot read current heating target")
                    return
                if prev != SOLAR_BOOST_TARGET_TEMP:
                    db.set("solar_boost_prev_target", prev)
                    if not self.__setHeatingTarget(SOLAR_BOOST_TARGET_TEMP):
                        return
                db.set("solar_boost_active", 1)
                self.log.info("solar boost ENGAGED: heating target %s -> %s °C" %
                              (prev, SOLAR_BOOST_TARGET_TEMP))
            return

        # surplus condition failed
        if not active:
            db.set("solar_boost_misses", 0)
            return

        misses += 1
        db.set("solar_boost_misses", misses)
        if misses < SOLAR_BOOST_RELEASE_MISSES:
            self.log.info(
                "solar boost: surplus dropped (%d/%d), holding boost engaged" %
                (misses, SOLAR_BOOST_RELEASE_MISSES))
            return

        # sustained loss of surplus -> release
        prev = utils.toInt(db.get("solar_boost_prev_target")) or 35
        if self.__setHeatingTarget(prev):
            db.set("solar_boost_active", 0)
            db.set("solar_boost_misses", 0)
            self.log.info("solar boost RELEASED: heating target -> %s °C" % prev)


    # -------------------------------------------------------------------
    # Roleta terasa nightly drift correction
    #
    # The terasa cover sometimes drifts off its desired partial-shade
    # position. Once per night after TERASA_CAL_HOUR we:
    #   1. read its current position
    #   2. if it's already inside [TERASA_CAL_OK_MIN..MAX], do nothing
    #   3. otherwise drive it fully closed (position=0), wait 5 s, then
    #      send position=TERASA_CAL_TARGET_PCT (18) so the firmware re-
    #      counts from the bottom limit and lands at a known spot.
    # The "ran today" flag lives in redis under terasa_cal_last_date.
    # -------------------------------------------------------------------

    def checkTerasaCalibration(self):
        db = conf.db.conn
        now = time.localtime()
        if now.tm_hour < TERASA_CAL_HOUR:
            return
        today = time.strftime("%Y-%m-%d", now)
        last = utils.toStr(db.get("terasa_cal_last_date"))
        if last == today:
            return

        try:
            import methods
        except Exception as e:
            self.log.warning("terasa cal: cannot import methods: %s" % e)
            return

        s = methods._blindStatus("terasa")
        pos = s.get("position")
        if pos is None:
            self.log.warning(
                "terasa cal: blind offline (msg=%s), will retry" % s.get("msg"))
            return  # don't mark today, retry on next iteration

        # Mark today AFTER we know the cover is reachable, so a flaky
        # tunnel doesn't burn the daily slot.
        db.set("terasa_cal_last_date", today)

        if TERASA_CAL_OK_MIN <= pos <= TERASA_CAL_OK_MAX:
            self.log.info(
                "terasa cal: position %d%% within [%d-%d], no action" %
                (pos, TERASA_CAL_OK_MIN, TERASA_CAL_OK_MAX))
            return

        self.log.info(
            "terasa cal: position %d%% out of [%d-%d], recalibrating" %
            (pos, TERASA_CAL_OK_MIN, TERASA_CAL_OK_MAX))

        r1 = methods.blinds_command(id="terasa", position=0)
        if not r1.get("ok"):
            self.log.warning("terasa cal: close failed: %s" % r1.get("msg"))
            return
        time.sleep(TERASA_CAL_PAUSE_SEC)
        r2 = methods.blinds_command(id="terasa", position=TERASA_CAL_TARGET_PCT)
        if not r2.get("ok"):
            self.log.warning("terasa cal: target set failed: %s" % r2.get("msg"))
            return
        self.log.info("terasa cal: set to %d%%" % TERASA_CAL_TARGET_PCT)


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
