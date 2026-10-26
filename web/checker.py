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
# Charging has priority: we engage the boost only when the battery is
# genuinely charging hard (real surplus), and release it the moment the
# pack starts discharging — running the TC off the battery is exactly
# what we don't want. The 10-min cadence keeps that from reacting to a
# single passing-cloud blip.
# ⚠ SOC here is the bank's CHARGE, counted in amp-hours by the BMS shunts and
# divided by the nominal pack capacities in conf.Battery.capacity_ah. It is not
# a voltage reading dressed up as a percentage, and it is the third scale these
# constants have lived on, so the history is worth keeping straight:
#
#   until 2026-10-25   the inverter's own batteryCapacity — a guess off the
#                      terminal voltage; reported 75 % where the packs said 42.
#   2026-10-25 (am)    load-compensated voltage map, after the inverter's
#                      current register turned out to read 0 below ~5 A.
#   2026-10-25 (pm)    coulomb counters, once the LFP had been calibrated
#                      against a full charge and its count could be trusted.
#
# Each move was re-anchored rather than retuned, so the features still fire
# where they always did. This last one was measured, not calculated: 13 days of
# 5-minute samples, each one's open-circuit bus voltage against the bank's
# counted charge at that moment.
#
#   constant                        voltage scale   ->  charge    samples
#   DAY_HP_SOC                        56 %  52.99 V     65 %        442
#   SOLAR_BOOST_SOC_MIN               72 %  54.70 V     82 %        112
#   SOLAR_BOOST_SOC_RELEASE           76 %  55.13 V     85 %        106
#   SOLAR_BOOST_SOC_HARD_RELEASE      52 %  52.56 V     58 %        456
#
# The gap is not a constant offset: the voltage map tracks the counters within
# a couple of points below about 60 % and then under-reads by 10 to 15, because
# the LFP clamps the bus and spends most of its charge inside a 150 mV band per
# cell. All four of these constants were sitting in that region. Retune against
# charge from here; do not convert a third time.
SOLAR_BOOST_SOC_MIN          = 82      # battery SOC [%] required to engage (high — so the
                                       # battery has plenty of headroom and we don't drain it)
SOLAR_BOOST_SOC_HARD_RELEASE = 58      # if SOC drops to this once boost is active, release
SOLAR_BOOST_MIN_PRODUCTION_W = 1500    # (informational) rough TC compressor draw at 50 °C
SOLAR_BOOST_CHARGE_MIN_A     = 15      # battery must be CHARGING at least this hard to ENGAGE
                                       # boost — genuine surplus, so adding the ~2 kW TC won't
                                       # flip the pack into discharge (priority is charging)
SOLAR_BOOST_DISCHARGE_MAX_A  = 1       # ENGAGE test only: the pack must not already be
                                       # draining before we add the ~2 kW TC
SOLAR_BOOST_DAYTIME_VOLT     = 100     # solarVoltage [V] threshold to call it daytime
SOLAR_BOOST_TARGET_TEMP      = 50      # heating target [°C] while parking surplus
SOLAR_BOOST_INTERVAL         = 600     # seconds between checks

# Second way in: the charge current is sitting on the inverter's own charge
# ceiling. Then the MPPT is throttling to that limit by definition and every
# further watt the array could make is being thrown away — which is surplus
# whatever the SOC says.
#
# The pair could not see this, because 150 A across two units was the whole
# array: hitting the cap and filling the pack happened at the same moment, so
# SOC alone was a sufficient test. One 10 kW unit behind the same 14.4 kWp
# reaches the cap long before the pack is full — on 2026-10-26 it sat at
# 154 A of 160 for three hours from 55 % SOC, and the boost was held off on
# the SOC gate the whole time with the array clipped.
# Counted over a sliding window rather than consecutively, which the first
# version of this got wrong. The check samples an instantaneous current once
# every ten minutes, and on a part-cloudy day that sample bounces hard: over
# 2026-10-26 10:25-12:25 it read 147, 58, 154, 38, 32, 106, 159, 68, 113, 117,
# 113, 152, 162 A against a 160 A cap. Clipped for much of it, yet never twice
# in a row until the SOC gate had opened anyway — so "two consecutive" would
# have delivered nothing at all. Two in any four does fire, at 10:45, which is
# the hour and three quarters of clipped array that prompted this.
SOLAR_BOOST_CHARGE_CAP_FRAC  = 0.90    # fraction of solarMaxChargingCurrent that counts
                                       # as "clipping" — the inverter's own regulation
                                       # wanders a few amps under the setpoint
SOLAR_BOOST_CAP_WINDOW       = 4       # checks remembered (40 min)
SOLAR_BOOST_CAP_HITS         = 2       # of them at the cap, to engage

# Redis keys holding the inverter snapshots. This list is deliberately allowed
# to be longer than the number of units actually installed: mqtt_bridge writes
# the keys with a TTL, so a unit whose daemon stops reporting simply drops out
# and "how many inverters are there" is answered by redis instead of by a 2
# hardcoded at every call site. That hardcoded 2 is exactly what made every
# average read half its true value when the parallel pair became a single unit
# on 2026-10-22 — the battery showed 24 V on a 48 V pack.
INVERTOR_KEYS = ("invertor_1", "invertor_2")

# Battery state for control decisions comes from the BMS shunts rather than
# from the inverter, for two measured reasons:
#   * the inverter's batteryCapacity is a guess off the terminal voltage. On
#     2026-10-25 it reported 75 % while the six packs reported 42/69/69/56/72/7.
#   * its current register is an integer that reads 0 below about 5 A, which is
#     precisely where DAY_HP_CHARGE_MIN_A (5) and DAY_HP_DISCHARGE_MAX_A (2)
#     sit — both tests were being made against a number with no resolution
#     there. The BMS shunts report milliamps.
# The derivation itself lives in utils.batteryState() so that methods.py can
# serve the panel the same numbers the controller acts on.
# --- release criteria -------------------------------------------------------
# Releasing on "the battery is discharging at all" made the controller test a
# quantity it controls itself, and it oscillated with a period of exactly
# SOLAR_BOOST_INTERVAL: engage -> TC ramps to 50 °C and draws ~2 kW -> that
# exceeds the surplus so the pack flips to a few amps of discharge -> next
# check releases -> TC backs off -> pack charges again -> engage. Observed
# 2026-10-14, four full cycles between 14:56 and 15:26, swinging the water
# target 32 <-> 50 °C each time, which is hard on the compressor.
#
# A few amps out of a FULL pack while the boost runs is the expected, correct
# state: the inverters are curtailing solar, and the boost is spending energy
# that would otherwise be thrown away. So release on things the boost cannot
# instantly fake instead — a minimum dwell, SOC actually falling, or a drain
# deep enough to mean the surplus is genuinely gone.
SOLAR_BOOST_MIN_ON_S         = 1800    # hold at least 30 min once engaged (only the hard
                                       # SOC floor may cut it short) — stops the limit cycle
                                       # and gives the TC time to do real work per engagement
SOLAR_BOOST_SOC_RELEASE      = 85      # SOC [%] this far below full = the pack really is
                                       # being drained, not just lagging the MPPT. Kept the
                                       # same few points above _SOC_MIN as before the rescale
                                       # — note that means a boost engaged just over the line
                                       # releases as soon as the dwell expires, which was
                                       # already true on the old scale (85 vs 90).
SOLAR_BOOST_DISCHARGE_DEEP_A = 20      # ~1 kW out of the pack: at that depth the surplus is
                                       # gone and we are running the TC off the battery
SOLAR_BOOST_DEEP_MISSES      = 2       # consecutive checks at that depth before releasing
HP_POWER_DEVICE_ID           = "bf2f6c60f5d1b15d9c6urw"   # kWh meter on the TC line (informational logging)

# --- garage gate -----------------------------------------------------------
# The garage is a dump, not a room: uninsulated doors, and its only job is to
# absorb surplus that would otherwise be curtailed. It must never be heated
# from the grid or the battery.
#
# Two conditions, and the second is the one that does the work. The buffer
# tank is the FIRST place surplus should go — it is small and the heat in it
# is directly useful — so the garage only qualifies once the tank is properly
# charged, not merely at its 38 °C working minimum.
#
# 55 °C measured as the right bar over 96 h: with the solar boost running the
# tank sits at a median 56.0 °C and clears 55 three-quarters of the time;
# without it the median is 39.0 and it clears 55 only 5 %. It separates real
# abundance from everything else by itself.
#
# What this would have saved, measured: on the night of 2026-10-18/19 the grid
# was on and the garage setpoint had been left at 19.75 °C against a room at
# ~19.2. It ran 8.3 h and took 4.17 kWh — 30 % of all heat that night — at
# 3.55 Kč/kWh, through uninsulated doors, in the dark.
# Two bars, not one. The garage loop is itself a load on the buffer, so with a
# single threshold the gate closes a few minutes after it opens: 2026-10-26 it
# opened at 55.0 °C at 13:02:10 and shut again at 54.0 °C at 13:07:34, having
# caused that degree itself. Letting the tank fall to 48 before closing keeps a
# 7 °C band, and 48 is still ten degrees above the buffer's working minimum, so
# the house loops never see the difference — a floor circuit wants 35-45 °C.
GARAGE_SENSOR_ID   = 10040010
GARAGE_TANK_MIN_C  = 55    # tank [°C] to OPEN the garage
GARAGE_TANK_OFF_C  = 48    # and to hold it open down to
GARAGE_DPS_TANK    = 108   # heat-pump tank temperature

# Night/day heat-pump schedule: every evening drop the HP water target so the TC
# doesn't over-heat the house and drain the battery overnight; in the day, once the
# battery is charged from solar, raise it back. Solar boost layers on top (bumps to
# SOLAR_BOOST_TARGET_TEMP while there's surplus, then falls back to whichever base
# the schedule has set).
#
# **The schedule sets the target only — never the mode** (owner, 2026-10-19). The
# pump runs its own mute/smart/strong logic and does it better than a rule here
# can; boost is the one place we are allowed to override it, and today it doesn't
# need to either. This used to write mute/smart alongside every target change,
# which fought the pump for no gain.
NIGHT_HP_EVENING_HOUR = 21     # local hour to switch to the night profile
NIGHT_HP_MORNING_HOUR = 7      # before this hour it's always night
NIGHT_HP_TARGET       = 32     # HP water target [°C] overnight / day-quiet
DAY_HP_TARGET         = 37     # HP water target [°C] in the day when solar is sufficient
DAY_HP_SOC            = 65     # battery SOC [%] needed before the HP may run hard (charge
                               # first). Re-anchored with the rescale — see the note above
                               # SOLAR_BOOST_SOC_MIN. Traces back to the eight DAY-FULL
                               # events of 21-22 Oct, which all fired at bus 53.7-53.9 V.
DAY_HP_SOC_HOLD_MARGIN = 19    # once day_full, hold it until SOC falls this far below the
                               # entry point. 15 on the inverter's scale, 12 on the voltage
                               # map, 19 in charge: the release point is bus 51.7 V, which
                               # is 46 % counted and 44 % mapped, and the entry point is
                               # 65 against 56. The span stretches because the voltage map
                               # compresses the top of the range, not because the hysteresis
                               # was widened.
DAY_HP_CHARGE_MIN_A   = 5      # battery must be CHARGING at least this hard to go day_full
                               # (not just "sun is up" — the pack has to actually be gaining)
DAY_HP_DISCHARGE_MAX_A = 2     # discharge above this drops day_full back to quiet (charge first)
HEATING_SCHED_INTERVAL = 300   # re-evaluate the profile at most this often [s] (anti-flap)

# ── Bathroom morning slot ────────────────────────────────────────────────
# The bathroom's air temperature is not what this is about. Above roughly
# 24.5 °C nobody notices another degree of air; what people notice is a warm
# floor underfoot after 05:00. The floor surface follows the water within
# minutes while the room air has a ten-hour time constant, so this is a
# floor-surface requirement expressed as a water schedule — not a setpoint.
#
# It therefore overrides the room's own vote on purpose. The bathroom sits
# above its target most of the night, so left to the thermostat the loop
# would stay shut and the floor would be cold exactly when it is walked on.
#
# Two things must happen together, and the second is the one easy to miss:
# the loop has to open AND the water has to be at working temperature.
# Measured 2026-10-19 on the night profile: tank 37 °C, flow 33, return 31.
# Opening the port alone would push 33 °C water round for a quarter of an
# hour and warm nothing — which is why this is a schedule mode and not just
# a forced valve.
MORNING_SLOT_START_MIN = 4 * 60 + 45   # 04:45 local — ~15 min of lead time
MORNING_SLOT_END_MIN   = 7 * 60        # 07:00, where the day schedule takes over
MORNING_SENSOR_ID      = 10246875      # koupelna
MORNING_HP_TARGET      = DAY_HP_TARGET # the same water the house uses by day
MORNING_MAX_ROOM_C     = 28            # safety ceiling. A forced loop ignores the
                                       # thermostat, so it needs *some* upper stop;
                                       # set well above the 24.5 that matters so it
                                       # never interferes in normal operation and
                                       # only catches a stuck sensor or a hot day.

# Terasa nightly drift correction: once after 23:00, if Roleta terasa
# isn't sitting at its expected partial position, fully close it and
# then re-target so the calibration stays consistent.
TERASA_CAL_HOUR              = 0       # check fires after midnight (= first tick when the date rolls over)
TERASA_CAL_OK_MIN            = 17
TERASA_CAL_OK_MAX            = 20
TERASA_CAL_TARGET_PCT        = 18
TERASA_CAL_FULL_TRAVEL_SEC   = 30   # max one-way travel; enough for the cover to reach a limit
TERASA_CAL_SETTLE_SEC        = 3    # extra breath after the limit before driving back


class Checker:

    def __init__(self, logger):
        self.log = logger


    def check(self):
        db = conf.db.conn

        self.__heatingCounter = utils.toInt(db.get("__heatingCounter")) + 1
        db.set("__heatingCounter", self.__heatingCounter)

        self.checkTemperature()
        self.checkLight()
        self.checkHeatingSchedule()
        self.checkSolarBoost()
        self.checkTerasaCalibration()


    # Night light is gated on PV POWER (V × I), not voltage alone.
    #
    # PV voltage isn't a reliable day/night signal on this array: at
    # night the inverter periodically probes the panels, which makes
    # solarVoltage briefly jump to 150-200 V even though no actual
    # current is flowing. The product (V*I) cleanly stays near zero
    # because the probe doesn't draw real current.
    #
    # Hysteresis bands + a small debounce counter on top:
    #   power ≥ 50 W   →  candidate "day" (light off)
    #   power ≤ 5 W    →  candidate "night" (light on)
    #   in between     →  hold current state
    # The candidate has to disagree with the actual relay state for
    # NIGHT_LIGHT_AGREE_N consecutive ticks (daemon ticks every ~1 s)
    # before we send the HTTP toggle.
    NIGHT_LIGHT_PV_ON_W    = 5     # below this watts → night → lights on
    NIGHT_LIGHT_PV_OFF_W   = 50    # above this watts → day → lights off
    NIGHT_LIGHT_AGREE_N    = 5     # consecutive readings before flipping

    def checkLight(self):
        db = conf.db.conn
        oldValue = utils.toStr(db.get("light_night_state"))

        solar_w = self.__solarPower()
        if solar_w is None:
            # No invertor data — fall back to time-of-day so the lights
            # don't get stuck if redis is empty.
            tm = utils.toInt(time.strftime("%H", time.localtime()))
            candidate = "0" if 8 <= tm <= 15 else "1"
        elif solar_w >= self.NIGHT_LIGHT_PV_OFF_W:
            candidate = "0"
        elif solar_w <= self.NIGHT_LIGHT_PV_ON_W:
            candidate = "1"
        else:
            # In the hysteresis dead-band: hold current state.
            candidate = oldValue or "1"

        if candidate == oldValue:
            db.set("light_agree_count", 0)
            return

        count = utils.toInt(db.get("light_agree_count")) + 1
        db.set("light_agree_count", count)
        if count < self.NIGHT_LIGHT_AGREE_N:
            return

        db.set("light_agree_count", 0)
        req = "/?p=%s&v=%s" % (1, candidate)
        data = self.sendReq(conf.Heating.hwIp, req)
        data = json.loads(data)
        newValue = data.get("v")
        db.set("light_night_state", newValue)
        self.log.info(
            "Set night light to: %s (solarP=%s, after %d ticks)" %
            (newValue,
             "%.0fW" % solar_w if solar_w is not None else "n/a",
             count))


    def __invertors(self):
        """Snapshots of every inverter that is currently reporting.

        Returns a list, possibly empty. Empty means no data — callers must
        treat it as "don't know", never as zero, because a missing inverter
        and an inverter reading zero demand opposite responses.
        """
        db = conf.db.conn
        units = []
        for key in INVERTOR_KEYS:
            try:
                raw = db.get(key)
            except Exception:
                continue
            if not raw:
                continue
            try:
                units.append(pickle.loads(raw))
            except Exception:
                continue
        return units


    def __batteryState(self):
        """One measured view of the battery for every control decision.

        Thin wrapper over utils.batteryState() — see there for what is read
        and why. Returns None when nothing is reporting, which callers must
        treat as "don't know", never as zero.
        """
        return utils.batteryState(
            conf.db.conn, self.__invertors(), conf.Battery)


    def __solarVoltage(self):
        """Highest solar string voltage [V] across the reporting invertors,
        or None if no invertor data is in redis yet. Each unit has its own
        MPPT, so this is a max and not a sum."""
        units = self.__invertors()
        if not units:
            return None
        return max(float(u.get("solarVoltage", 0)) for u in units)


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
                # External sensors (e.g. the greenhouse) are display-only —
                # their temperature must not vote in changeHeatingState
                # and they don't drive a manifold port.
                if roomId in conf.HeatingSensors.external:
                    continue
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
            
            # A hung manifold (ESP web server stops answering while still
            # pinging) must NOT block the heating relay or the rest of the
            # daemon — handle each independently.
            # The garage is last in the queue and may only take surplus —
            # see the GARAGE_* constants. Applied here rather than in the
            # demand loop so the thermostat logic stays one thing and the
            # priority rule stays another.
            # The bathroom runs before the garage, which is the priority order
            # the owner gave: bathroom first, garage last. They touch different
            # ports so the order is documentation rather than mechanism — but
            # if a third rule ever competes for the same loop, this is where
            # the ranking lives.
            try:
                self.__forceBathroomLoop(db, result, sensors)
            except Exception as e:
                self.log.warning("bathroom morning slot failed (%s) — "
                                 "falling back to its thermostat" % e)

            try:
                self.__gateGarage(db, result, sensors)
            except Exception as e:
                # Fail closed. This handler is the last line — the gate
                # already catches its own failures — but "leave the demand
                # as-is" here would have quietly turned the garage back on
                # the moment anything in the gate broke, which is the exact
                # outcome the gate exists to prevent.
                self.log.warning("garage gate failed (%s) — closing the garage" % e)
                try:
                    result[sensors.index(GARAGE_SENSOR_ID)] = 0
                except Exception:
                    pass

            try:
                self.changeManifoldStatus(result, sensors)
            except Exception as e:
                self.log.warning("Manifold update failed (%s) — relay still handled" % e)
            try:
                self.changeHeatingState(1 if sum(result) > 0 else 0)
            except Exception as e:
                self.log.warning("Heating relay update failed: %s" % e)


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
            data = self.sendReq(conf.HeatingSensors.manifoldIp, "/" + newValue, timeout=2)
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


    def sendReq(self, ip, req, timeout=5):

        if (conf.Lights.httpConn == 1):

            conn = http.client.HTTPConnection(ip, timeout=timeout)
            try:
                conn.request("GET", req)
                res  = conn.getresponse()
                data = res.read()
                self.log.info("Request to: http://%s%s <%s %s>" % (
                    ip, req, res.status, res.reason))
                return data
            finally:
                conn.close()


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

        units = self.__invertors()
        if not units:
            self.log.debug("solar boost: invertor data not available")
            return

        # --- read all three signals at once ---
        # Battery state from the BMS shunts where available; see
        # __batteryState() for why not from the inverter.
        bat = self.__batteryState()
        if bat is None or bat["soc"] is None:
            self.log.debug("solar boost: battery state not available")
            return
        soc = bat["soc"]
        discharge_a = bat["discharge_a"]

        # solar voltage > threshold on either string indicates daytime;
        # the actual produced wattage is unreliable as a surplus signal
        # because the MPPT throttles to match load when battery is full.
        solar_v = max(float(u.get("solarVoltage", 0)) for u in units)

        # informational only — logged but not used for the decision
        solar_w = self.__solarPower() or 0
        hp_w = self.__hpPower()
        hp_on, hp_workmode = self.__hpMode()

        active = utils.toInt(db.get("solar_boost_active"))

        # Only run the heating boost while the HP is in HEATING mode. Never
        # engage (or power it on) during cooling; if the mode can't be read,
        # stay safe and do nothing. If a boost was left active, release it.
        if hp_workmode != "heat":
            if active:
                self.__releaseSolarBoost(db, "HP not in heating mode (%s)" % hp_workmode)
            else:
                self.log.debug("solar boost: HP workmode=%s (not heat) — skipping" % hp_workmode)
            return

        charge_a = bat["charge_a"]

        # Is the array clipped against the charge limit? Summed over the units
        # because the cap is per-inverter while charge_a is the whole bank.
        cap_a = sum(float(u.get("solarMaxChargingCurrent", 0)) for u in units)
        at_cap = cap_a > 0 and charge_a >= SOLAR_BOOST_CHARGE_CAP_FRAC * cap_a
        window = (utils.toStr(db.get("solar_boost_cap_window"))
                  + ("1" if at_cap else "0"))[-SOLAR_BOOST_CAP_WINDOW:]
        db.set("solar_boost_cap_window", window)
        cap_hits = window.count("1")

        # Two ways to know the panels have headroom, and either will do:
        #   (a) the pack is near full and still genuinely gaining charge, so
        #       adding the ~2 kW TC won't flip it into discharge;
        #   (b) the charge current has been pinned to the cap, so the MPPT is
        #       already throttling and the extra is being wasted.
        # Both still require daylight and a pack that isn't already draining.
        by_soc = soc >= SOLAR_BOOST_SOC_MIN and charge_a >= SOLAR_BOOST_CHARGE_MIN_A
        by_cap = cap_hits >= SOLAR_BOOST_CAP_HITS
        surplus = (
            (by_soc or by_cap)
            and discharge_a <= SOLAR_BOOST_DISCHARGE_MAX_A
            and solar_v >= SOLAR_BOOST_DAYTIME_VOLT
        )

        self.log.info(
            "Solar boost: SOC=%.0f%%(%s) charge=%.1fA/%.0fA disch=%.1fA solarV=%.0fV solar=%.0fW HP=%s power=%s surplus=%s(soc=%s cap=%s of %d) active=%s" % (
                soc, bat["source"], charge_a, cap_a, discharge_a, solar_v, solar_w,
                ("%.0fW" % hp_w if hp_w is not None else "?"),
                hp_on, surplus, by_soc, window, SOLAR_BOOST_CAP_HITS, bool(active)))

        if active:
            # See the release-criteria note by the constants: the boost itself
            # pushes the pack into a shallow discharge, so that signal cannot be
            # the release test or the controller chases its own tail.
            held_s = now_ts - utils.toInt(db.get("solar_boost_on_since"))
            on_cap = utils.toStr(db.get("solar_boost_reason")) == "cap"

            # Neither SOC test can apply to a boost engaged on the clipped
            # array: it started below both lines on purpose, so they would
            # throw it straight back out and it would re-engage ten minutes
            # later, flapping the water target all afternoon. What ends that
            # one is the surplus going away, which the deep-drain test below
            # sees — and it skips the dwell for that test too, because with a
            # half-empty pack stopping ten minutes early is the cheaper
            # mistake.
            if not on_cap:
                # The hard SOC floor always wins, dwell or not.
                if soc < SOLAR_BOOST_SOC_HARD_RELEASE:
                    self.__releaseSolarBoost(
                        db, "SOC %.0f%% below hard floor %d%%"
                        % (soc, SOLAR_BOOST_SOC_HARD_RELEASE))
                    return

                if held_s < SOLAR_BOOST_MIN_ON_S:
                    self.log.debug("solar boost: holding (%ds of %ds dwell)"
                                   % (held_s, SOLAR_BOOST_MIN_ON_S))
                    return

                if soc < SOLAR_BOOST_SOC_RELEASE:
                    self.__releaseSolarBoost(
                        db, "SOC fell to %.0f%% (< %d%%) — pack is being drained"
                        % (soc, SOLAR_BOOST_SOC_RELEASE))
                    return

            # A deep drain has to persist: one reading can be a cloud passing
            # over while the compressor happens to be at full tilt.
            if discharge_a > SOLAR_BOOST_DISCHARGE_DEEP_A:
                misses = utils.toInt(db.get("solar_boost_misses")) + 1
                db.set("solar_boost_misses", misses)
                if misses >= SOLAR_BOOST_DEEP_MISSES:
                    self.__releaseSolarBoost(
                        db, "draining %.1fA for %d checks — surplus is gone"
                        % (discharge_a, misses))
                return
            db.set("solar_boost_misses", 0)
            return

        # not active — engage only on a genuine charging surplus
        if surplus:
            prev = self.__heatingTarget()
            if prev is None:
                self.log.warning("solar boost: cannot read current heating target")
                return
            if prev != SOLAR_BOOST_TARGET_TEMP:
                db.set("solar_boost_prev_target", prev)
                if not self.__setHeatingTarget(SOLAR_BOOST_TARGET_TEMP):
                    return
            # Raising the target alone won't start a switched-off pump — power
            # it on too, and remember we did so we only switch off what we
            # switched on (never a pump the user started).
            if hp_on is False:
                if self.__setHpPower(True):
                    db.set("solar_boost_powered_on", 1)
                    self.log.info("solar boost: HP was off -> turned ON")
            else:
                db.set("solar_boost_powered_on", 0)
            db.set("solar_boost_active", 1)
            db.set("solar_boost_on_since", now_ts)
            db.set("solar_boost_misses", 0)
            # Which test let it in decides which tests may throw it out again.
            db.set("solar_boost_reason", "soc" if by_soc else "cap")
            self.log.info("solar boost ENGAGED on %s: heating target -> %s °C "
                          "(SOC=%.0f%%, charge=%.1fA of %.0fA cap, holding at least %d min)"
                          % ("SOC" if by_soc else "charge cap", SOLAR_BOOST_TARGET_TEMP,
                             soc, charge_a, cap_a, SOLAR_BOOST_MIN_ON_S // 60))


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

    # State machine driven by the 1-Hz daemon tick, so a single
    # calibration doesn't park the whole checker for ~63 s and stall
    # heating / solar-boost decisions. Phase + tick count live in Redis
    # so a daemon restart mid-cycle picks up where we left off instead
    # of leaving the cover stuck halfway.
    #
    # Phases:
    #   ""           idle — gate on hour + once-per-day flag
    #   "closing"    drive=close sent; wait FULL_TRAVEL ticks
    #   "settling"   limit reached; wait SETTLE ticks for switch reset
    #   "targeting"  position=TARGET_PCT sent; wait FULL_TRAVEL ticks
    #
    # Each tick advances by 1 (daemon loop sleeps 1 s between checks).
    TERASA_PHASE_KEY = "terasa_cal_phase"
    TERASA_TICK_KEY  = "terasa_cal_tick"

    def _terasaSetPhase(self, db, phase, tick=0):
        db.set(self.TERASA_PHASE_KEY, phase)
        db.set(self.TERASA_TICK_KEY, tick)

    def checkTerasaCalibration(self):
        db = conf.db.conn
        phase = utils.toStr(db.get(self.TERASA_PHASE_KEY))

        # ----- mid-cycle phases: advance the counter, move on at deadline
        if phase == "closing":
            tick = utils.toInt(db.get(self.TERASA_TICK_KEY)) + 1
            db.set(self.TERASA_TICK_KEY, tick)
            if tick >= TERASA_CAL_FULL_TRAVEL_SEC:
                self._terasaSetPhase(db, "settling")
                self.log.info("terasa cal: closed, settling %d s" %
                              TERASA_CAL_SETTLE_SEC)
            return

        if phase == "settling":
            tick = utils.toInt(db.get(self.TERASA_TICK_KEY)) + 1
            db.set(self.TERASA_TICK_KEY, tick)
            if tick < TERASA_CAL_SETTLE_SEC:
                return
            try:
                import methods
            except Exception as e:
                self.log.warning("terasa cal: cannot import methods: %s" % e)
                self._terasaSetPhase(db, "")
                return
            r = methods.blinds_command(id="terasa",
                                       position=TERASA_CAL_TARGET_PCT)
            if not r.get("ok"):
                self.log.warning("terasa cal: target set failed: %s" %
                                 r.get("msg"))
                self._terasaSetPhase(db, "")
                return
            self.log.info("terasa cal: target %d%% sent, %d s travel" %
                          (TERASA_CAL_TARGET_PCT, TERASA_CAL_FULL_TRAVEL_SEC))
            self._terasaSetPhase(db, "targeting")
            return

        if phase == "targeting":
            tick = utils.toInt(db.get(self.TERASA_TICK_KEY)) + 1
            db.set(self.TERASA_TICK_KEY, tick)
            if tick >= TERASA_CAL_FULL_TRAVEL_SEC:
                self.log.info("terasa cal: settled at target %d%%" %
                              TERASA_CAL_TARGET_PCT)
                self._terasaSetPhase(db, "")
            return

        # ----- idle: decide whether to start a fresh cycle tonight
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
            return  # don't mark today, retry on next tick

        # Mark today AFTER we know the cover is reachable, so a flaky
        # tunnel doesn't burn the daily slot.
        db.set("terasa_cal_last_date", today)

        if TERASA_CAL_OK_MIN <= pos <= TERASA_CAL_OK_MAX:
            self.log.info(
                "terasa cal: target %d%% already within [%d-%d], no action" %
                (pos, TERASA_CAL_OK_MIN, TERASA_CAL_OK_MAX))
            return

        # The cover only exposes a target percent (percent_control) over
        # both local Tuya and the cloud — there is no percent_state on
        # this device. We therefore can't read actual physical position;
        # only the last value we set. The reliable way to land at a
        # known partial position is:
        #   1. drive to the bottom limit (DPS 1 = "close") and wait for
        #      a full travel to actually complete — the firmware accepts
        #      percent commands again only after the motor has stopped.
        #      A close from anywhere takes up to ~25 s.
        #   2. wait a couple of seconds extra for the limit-switch reset.
        #   3. send the target percent (DPS 2). The cover then drives
        #      from the now-zeroed bottom up to the requested percent.
        #
        # An open->percent variant doesn't work for this cover: travel
        # ratios from the top end up off-target. Going from 0 up to the
        # target is the only sequence that lands consistently.
        self.log.info(
            "terasa cal: target %d%% out of [%d-%d], recalibrating from bottom" %
            (pos, TERASA_CAL_OK_MIN, TERASA_CAL_OK_MAX))

        r1 = methods.blinds_command(id="terasa", direction="close")
        if not r1.get("ok"):
            self.log.warning("terasa cal: close failed: %s" % r1.get("msg"))
            return
        self.log.info("terasa cal: closing, %d s travel" %
                      TERASA_CAL_FULL_TRAVEL_SEC)
        self._terasaSetPhase(db, "closing")


    # ---- solar-boost helpers -----------------------------------------

    def __batterySoc(self):
        """Load-compensated state of charge in percent, or None.

        Thin wrapper kept for the call sites that only want the one number;
        __batteryState() is where it is actually derived and why.
        """
        bat = self.__batteryState()
        return bat["soc"] if bat else None


    def __solarPower(self):
        """Total solar input power (W) summed across both invertors,
        or None if no data."""
        units = self.__invertors()
        if not units:
            return None
        # Prefer solarPowerTotal where the publisher provides it. On the 10 kW
        # unit the protocol reports one of two MPPTs, so current x voltage is
        # roughly half the truth; invertor.py reconstructs the rest from the
        # battery and load flows. Fall back to the product for any unit that
        # does not publish the field yet.
        total = 0.0
        for u in units:
            est = u.get("solarPowerTotal")
            if est is None:
                est = float(u.get("solarCurrent", 0)) * float(u.get("solarVoltage", 0))
            total += float(est)
        return total


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


    def __hpMode(self):
        """(power_on, work_mode) of the heat pump via the local Tuya tunnel.
        power_on is True/False/None, work_mode is 'heat'/'cool'/None."""
        try:
            import methods
            dps = methods._hpDps() or {}
            return (dps.get(str(methods.DPS_POWER)),
                    dps.get(str(methods.DPS_WORK_MODE)))
        except Exception as e:
            self.log.warning("hp mode read failed: %s" % e)
            return None, None

    def __hpTankTemp(self):
        """Buffer tank temperature [°C] from the heat pump, or None."""
        try:
            import methods
            dps = methods._hpDps() or {}
            v = dps.get(str(GARAGE_DPS_TANK))
            return float(v) if v is not None else None
        except Exception as e:
            self.log.warning("hp tank read failed: %s" % e)
            return None

    def __garageAllowed(self, db):
        """(allowed, reason) — may the garage loop open right now?

        See the GARAGE_* constants for why these two conditions and not a
        temperature threshold of its own. Fails closed: if the tank cannot be
        read we do not heat, because the whole point is to spend only surplus
        and an unknown tank is not evidence of surplus.
        """
        if not utils.toInt(db.get("solar_boost_active")):
            return False, "no solar surplus (boost off)"
        tank = self.__hpTankTemp()
        if tank is None:
            return False, "tank temperature unreadable"
        # Hysteresis on the tank only. The surplus test above stays immediate:
        # the moment the boost drops, the garage shuts, whatever the buffer
        # holds — that is the solar-only guarantee and it is not negotiable
        # against a bit of valve chatter.
        if utils.toStr(db.get("garage_gate_state")) == "open":
            if tank < GARAGE_TANK_OFF_C:
                return False, "tank %.1f < %d °C — buffer drawn down" % (
                    tank, GARAGE_TANK_OFF_C)
        elif tank < GARAGE_TANK_MIN_C:
            return False, "tank %.1f < %d °C — buffer not charged yet" % (
                tank, GARAGE_TANK_MIN_C)
        return True, "tank %.1f °C" % tank

    def __morningSlot(self):
        """True while the bathroom morning slot should be running."""
        t = time.localtime()
        return (MORNING_SLOT_START_MIN
                <= t.tm_hour * 60 + t.tm_min
                < MORNING_SLOT_END_MIN)

    def __forceBathroomLoop(self, db, result, sensors):
        """Hold the bathroom loop open through the morning slot. Mutates `result`.

        Fails **open**, which is the opposite of the garage gate, and the
        asymmetry is the point: if this breaks, the bathroom falls back to its
        own thermostat — exactly the behaviour we had before — and the cost is
        one cool morning. The garage's failure mode costs a night of grid
        electricity, so that one fails closed. Same house, opposite defaults,
        because the two mistakes are not the same size.
        """
        prev = utils.toStr(db.get("morning_slot_state"))
        if not self.__morningSlot():
            if prev:
                db.delete("morning_slot_state")
                self.log.info("bathroom morning slot: END")
            return

        try:
            i = sensors.index(MORNING_SENSOR_ID)
        except ValueError:
            return                      # bathroom sensor offline, nothing to force

        room_c = None
        try:
            room_c = float(pickle.loads(
                db.get("temp_sensor_%s" % MORNING_SENSOR_ID)).get("temperature"))
        except Exception:
            pass                        # unreadable: fall through and still heat

        if room_c is not None and room_c > MORNING_MAX_ROOM_C:
            state = "capped"
            reason = "room %.1f > %d °C" % (room_c, MORNING_MAX_ROOM_C)
        else:
            result[i] = 1
            state = "forced"
            reason = ("room %.1f °C" % room_c if room_c is not None
                      else "room temperature unreadable — heating anyway")

        if state != prev:
            db.set("morning_slot_state", state)
            self.log.info("bathroom morning slot %s: %s" % (state.upper(), reason))

    def __gateGarage(self, db, result, sensors):
        """Zero the garage's demand unless it is allowed. Mutates `result`.

        Logs only on a change of verdict — this runs on every ~1 s tick.

        **Fails closed at every level**, deliberately: an unreadable tank, a
        Redis blip, a bug in here — anything that stops us *proving* surplus
        leaves the garage shut. The asymmetry is the whole argument. A wrong
        "blocked" costs a cool slab in the room that is last in the queue
        anyway; a wrong "open" sends a night of heat through uninsulated
        doors on grid electricity (measured: 11.07 kWh in 20 h, 30 % of one
        night's heat). So the order below matters — the demand is zeroed
        before any bookkeeping that could raise.
        """
        try:
            i = sensors.index(GARAGE_SENSOR_ID)
        except ValueError:
            return                      # garage sensor offline: no port to gate
        if not result[i]:
            # Not asking for heat. Drop the hysteresis latch on the way out:
            # it exists to hold the gate open while the garage loop is drawing
            # the buffer down, and a closed loop draws nothing. Left latched,
            # it would admit the next request at the lower bar.
            if utils.toStr(db.get("garage_gate_state")) == "open":
                db.set("garage_gate_state", "blocked")
            return

        try:
            allowed, reason = self.__garageAllowed(db)
        except Exception as e:
            allowed, reason = False, "gate check failed (%s)" % e

        if not allowed:
            result[i] = 0

        try:
            prev = utils.toStr(db.get("garage_gate_state"))
            now = "open" if allowed else "blocked"
            if now != prev:
                db.set("garage_gate_state", now)
                self.log.info("garage gate %s: %s" % (now.upper(), reason))
        except Exception as e:
            self.log.warning("garage gate bookkeeping failed: %s" % e)

    def __setHpPower(self, on):
        """Turn the heat pump on/off explicitly (not a toggle). True on success."""
        try:
            import methods
            methods.hpTuya.set_value(methods.DPS_POWER, bool(on))
            return True
        except Exception as e:
            self.log.error("hp power set failed: %s" % e)
            return False

    def __releaseSolarBoost(self, db, reason=""):
        """Restore the heating target to the night/day schedule's current base (so we
        don't fall back to a stale snapshot) and, if WE powered the heat pump on, switch
        it back off. Idempotent, used by every release path."""
        prev = self.__scheduledBaseTarget()
        self.__setHeatingTarget(prev)
        if utils.toInt(db.get("solar_boost_powered_on")):
            if self.__setHpPower(False):
                self.log.info("solar boost: HP turned OFF (we had powered it on)")
            db.set("solar_boost_powered_on", 0)
        db.set("solar_boost_active", 0)
        db.set("solar_boost_misses", 0)
        db.set("solar_boost_on_since", 0)
        self.log.info("solar boost RELEASED: heating target -> %s °C (%s)" % (prev, reason))

    def __heatingTarget(self):
        """Current heating target temp (PG1[4]) in °C, or None."""
        ints = self.__pgRead(1)
        return ints[4] if ints else None


    def __setHeatingTarget(self, value):
        """Mutate PG1[4] and push it to the heat pump. Returns True on success.
        Always keeps the UI cache (heatpump_status / tablet read
        heatpump_status_heating_target_water_temp) in sync with the pump's REAL
        target — including when the write is a no-op or FAILS (e.g. the pump is
        unreachable on the LAN) — so the UI never shows a phantom target the pump
        never accepted."""
        value = int(value)
        ints = self.__pgRead(1)
        if ints is None:
            return False
        current = ints[4]
        if current == value:
            self.__cacheHeatingTarget(value)      # already right; make sure cache agrees
            return True
        ints[4] = value
        if self.__pgWrite(1, ints):
            self.__cacheHeatingTarget(value)
            return True
        # write failed -> reflect the pump's REAL (unchanged) target, not our wish
        self.__cacheHeatingTarget(current)
        self.log.warning("heating target write FAILED (pump unreachable?); real target stays %s" % current)
        return False

    def __cacheHeatingTarget(self, value):
        try:
            conf.db.conn.set("heatpump_status_heating_target_water_temp", int(value))
        except Exception:
            pass

    def __setHpMode(self, mode):
        """Set HP mode: 'smart' | 'mute' | 'strong'. True on success.

        **Deliberately unused.** The pump runs its own mode logic and the
        schedule must not fight it (owner, 2026-10-19); solar boost is the only
        place allowed to override, and it doesn't need to today. Kept because
        that exception is the one plausible caller — not because anything has
        been left half-done.
        """
        try:
            import methods
            methods.heatpump_setMode(mode=mode)
            return True
        except Exception as e:
            self.log.warning("hp mode set failed: %s" % e)
            return False

    def __scheduledBaseTarget(self):
        """Current base HP water target per the night/day schedule — used by the
        solar-boost release so it falls back to the right base, not a stale snapshot.
        Only the full-day profile uses the day target; night and day-quiet stay low."""
        mode = utils.toStr(conf.db.conn.get("heating_sched_mode")) or "night"
        return DAY_HP_TARGET if mode == "day_full" else NIGHT_HP_TARGET

    def checkHeatingSchedule(self):
        """Night / morning / day-quiet / day-full HP profile. Priority is charging
        the battery, so the TC sits on a low water target by default and only rises
        when solar is genuinely sufficient:
          - NIGHT  (evening..morning)          -> NIGHT_HP_TARGET
          - MORNING (bathroom floor slot)      -> MORNING_HP_TARGET
          - DAY, battery not charging          -> NIGHT_HP_TARGET  (charge first)
          - DAY, battery charged + charging    -> DAY_HP_TARGET
        Sets the **target only** — the pump owns mute/smart/strong (see the
        NIGHT_HP_* block). Priority is charging: while the battery isn't charging
        (no sun yet / overcast) the HP stays on the low night target so it doesn't
        ramp up and drain the pack off-solar; it only raises to the day target
        once the battery is genuinely charging. 'Charging' = SoC high enough AND
        positive battery charge current AND not discharging, with hysteresis + a
        dwell throttle so passing clouds don't flap the profile.
        Skips while solar boost is active (boost owns the target; it falls back to the
        base we set here when it releases, and layers the 50 °C boost on a big surplus)."""
        db = conf.db.conn
        if utils.toInt(db.get("solar_boost_active")):
            return
        hour = time.localtime().tm_hour
        mode = utils.toStr(db.get("heating_sched_mode"))   # "" until first run
        day_hours = NIGHT_HP_MORNING_HOUR <= hour < NIGHT_HP_EVENING_HOUR

        # dwell throttle: re-evaluate (and thus possibly switch the HP) at most every
        # HEATING_SCHED_INTERVAL — but never block the evening/morning night flip.
        now = int(time.time())
        last = utils.toInt(db.get("heating_sched_ts"))
        if mode and day_hours and last and (now - last) < HEATING_SCHED_INTERVAL:
            return

        bat = self.__batteryState()
        if bat and bat["soc"] is not None:
            soc = bat["soc"]
            charge_a = bat["charge_a"]
            discharge_a = bat["discharge_a"]
            src = bat["source"]
        else:
            # Nothing is reporting. Stay on the cautious side: unknown SOC
            # and a discharge current high enough that nothing opportunistic
            # starts on the strength of a reading we do not have.
            soc, charge_a, discharge_a, src = None, 0.0, 99.0, "none"

        if not day_hours:
            # The morning slot lives inside the night window and outranks it:
            # see the MORNING_* constants. It is not throttled, because the
            # dwell throttle above only applies during day_hours.
            want = "morning" if self.__morningSlot() else "night"
        elif soc is None:
            want = "day_quiet"                      # no data -> stay gentle, charge first
        elif mode == "day_full":
            # already full: hold it until the battery is charged no more / starts draining
            want = ("day_full" if (soc >= DAY_HP_SOC - DAY_HP_SOC_HOLD_MARGIN
                                   and discharge_a <= DAY_HP_DISCHARGE_MAX_A)
                    else "day_quiet")
        else:
            # ramp to full only once the battery is charged AND genuinely charging
            # (positive charge current, not just "the sun is up") — charging first
            want = ("day_full" if (soc >= DAY_HP_SOC
                                   and charge_a >= DAY_HP_CHARGE_MIN_A
                                   and discharge_a <= DAY_HP_DISCHARGE_MAX_A)
                    else "day_quiet")

        db.set("heating_sched_ts", now)
        if want == mode:
            return
        socs = "%.0f%%" % soc if soc is not None else "n/a"
        if want == "day_full":
            self.__setHeatingTarget(DAY_HP_TARGET)
            self.log.info("HP schedule: DAY-FULL -> %s C (SoC=%s[%s] charge=%.1fA disch=%.1fA)"
                          % (DAY_HP_TARGET, socs, src, charge_a, discharge_a))
        elif want == "morning":
            # Warm the water so the bathroom loop has something worth
            # circulating. Target only — the pump picks its own mode.
            self.__setHeatingTarget(MORNING_HP_TARGET)
            self.log.info("HP schedule: MORNING -> %s C (bathroom floor slot)"
                          % MORNING_HP_TARGET)
        elif want == "day_quiet":
            # Battery isn't charging (no real sun yet / overcast) -> keep the low
            # night target so the HP doesn't ramp up and drain the battery
            # off-solar. Charging has priority; we raise to the day target only
            # once the battery is genuinely charging (-> day_full). On a cold dark
            # morning this means the house stays gentle until the sun catches up.
            self.__setHeatingTarget(NIGHT_HP_TARGET)
            self.log.info("HP schedule: DAY-QUIET -> %s C (SoC=%s[%s] charge=%.1fA disch=%.1fA)"
                          % (NIGHT_HP_TARGET, socs, src, charge_a, discharge_a))
        else:  # night
            self.__setHeatingTarget(NIGHT_HP_TARGET)
            self.log.info("HP schedule: NIGHT -> %s C (SoC=%s[%s] charge=%.1fA disch=%.1fA)"
                          % (NIGHT_HP_TARGET, socs, src, charge_a, discharge_a))
        db.set("heating_sched_mode", want)


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
                local_key=dev.get("key"),
                version=float(dev.get("ver", "3.3")))
            d.set_socketTimeout(2)
            b64 = base64.b64encode(struct.pack(">20i", *ints)).decode()
            r = d.set_value(117 + group_idx, b64)
            # tinytuya returns an {'Error':..,'Err':..} dict on a failed local
            # exchange instead of raising — treat that as a real failure so the
            # caller doesn't cache a target the pump never got.
            if isinstance(r, dict) and (r.get("Error") or r.get("Err")):
                self.log.warning("pg write: local device unreachable/error: %s" % r)
                return False
            return True
        except Exception as e:
            self.log.error("pg write failed: %s" % e, exc_info=True)
            return False
