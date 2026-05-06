"""
An entire file for you to expand. Add methods here, and the client should be
able to call them with json-rpc without any editing to the pipeline.
"""
#import RPi.GPIO as gpio

from config import conf, sendReq
import utils
import pickle
import http.client
import logging
import tinytuya
import pandas as pd
import json


log = logging.getLogger('web')

HP_DEVICE_ID = "bf06f140ee20807fdaalyq"

hpTuya = tinytuya.OutletDevice(
    dev_id=HP_DEVICE_ID,
    address=conf.Tuya.devices.get(HP_DEVICE_ID)["ip"],
    version=conf.Tuya.devices.get(HP_DEVICE_ID)["ver"]
)

# Tuya DPS codes for the heat pump
DPS_POWER             = 1    # on/off
DPS_MODE              = 2    # smart / mute / strong
DPS_WORK_MODE         = 5    # heat / cool
DPS_TEMP_UNIT         = 6    # "c" or "f" — toggling rescales every temperature in pg1..pg7
DPS_CURRENT           = 112  # actual current draw [A]
DPS_PARAMETER_GROUP_1 = 118  # base64-encoded settings blob, cloud-only DP

# parameter_group_1 .. parameter_group_7 are 80-byte base64 blobs containing
# 20 big-endian int32 values each. The DP is only readable through the Tuya
# cloud API (the local tunnel does not expose it in status()), but it IS
# writable through the local tunnel via hpTuya.set_value(118, <base64>).
PARAM_GROUP_INTS  = 20
PARAM_GROUP_BYTES = PARAM_GROUP_INTS * 4

# parameter_group_1 — index meanings, cross-checked against the official
# manufacturer manual. P-codes refer to the System Parameters list and
# F-codes to the Function Parameters list (Power World "EVI DC Inverter
# Heat Pump (with WIFI APP)" operating manual, section 3, pp. 33-34).
PG1_COOLING_RETURN_DIFF  = 0   # P01: return water vs cooling target diff [°C]
PG1_DHW_RETURN_DIFF      = 1   # P02: return water vs DHW target diff [°C]
PG1_DHW_TARGET_TEMP      = 2   # P03: hot water (DHW) setting temp [°C]
PG1_COOLING_TARGET_TEMP  = 3   # P04: cooling setting temp [°C]
PG1_HEATING_TARGET_TEMP  = 4   # P05: heating setting temp [°C]
PG1_WATER_TEMP_COMP      = 5   # P08: water temperature compensation [°C]
PG1_DISINFECT_CYCLE_DAYS = 6   # P17: high-temp disinfection cycle [days] (0 = disabled)
PG1_DISINFECT_START_HOUR = 7   # P18: high-temp disinfection start hour
PG1_DISINFECT_SUSTAIN_MIN = 8  # P19: high-temp disinfection sustain time [minutes]
PG1_DISINFECT_TARGET_TEMP = 9  # P20: high-temp disinfection target temperature [°C]
PG1_DISINFECT_HP_TEMP    = 10  # P21: heat pump's setting temp for disinfection [°C]
PG1_HEATING_AUTO_ADJUST  = 11  # P22: heating target temp auto adjust (0 = off, 1 = on)
PG1_HEATING_COMP_AMB_TEMP = 12 # P23: heating compensation reference ambient [°C]
PG1_TARGET_TEMP_COMP_COEF = 13 # P24: target temp compensation coefficient (1 unit = 0.1)
PG1_FREQ_AFTER_CONST_TEMP = 14 # P25: compressor freq mode after constant temp (0=decrease, 1=non-decrease)
PG1_PIPE_HEATER_AMB_TEMP = 15  # P26: pipeline e-heater enable ambient [°C]
PG1_DHW_HEATER_START_TIME = 16 # P27: water tank e-heater entry time [minutes]
PG1_FUNCTION_MODE        = 17  # F01: heat pump function (1=heat, 2=H+C, 3=H+DHW, 4=H+C+DHW)
PG1_PUMP_AFTER_TARGET    = 18  # F02: pump status after target (0=intermittent, 1=all time, 2=stop at const temp)
PG1_PUMP_CYCLE_MIN       = 19  # F03: pump on/off cycle [minutes]
# parameter_group_1 fully mapped.

# Legacy alias — pg1[0] was originally labelled "heating_return_diff"
# until the manual showed P01 is actually for the cooling target.
PG1_HEATING_RETURN_DIFF = PG1_COOLING_RETURN_DIFF
PG1_FREQ_AFTER_TARGET = PG1_FREQ_AFTER_CONST_TEMP

# parameter_group_2 — write path goes through DPS 119 (verified). P-codes
# refer to the System Parameters list in the manufacturer manual.
PG2_DC_PUMP_MODE         = 0   # F04: DC pump mode (0=no start, 1=auto, 2=manual)
PG2_DC_PUMP_MANUAL_SPEED = 1   # F06: DC water pump manual speed [%]
PG2_DEFROST_FREQ         = 2   # P09: defrosting frequency [Hz]
PG2_DEFROST_PERIOD       = 3   # P10: defrosting period [minutes]
PG2_DEFROST_ENTER_TEMP   = 4   # P11: defrosting enter temp [°C]
PG2_DEFROST_TIME         = 5   # P12: defrosting time (max duration) [minutes]
PG2_DEFROST_EXIT_TEMP    = 6   # P13: defrost exit temp [°C]
PG2_DEFROST_EVAP_DIFF_1  = 7   # P14: env vs evaporator-coil temp diff 1 [°C]
PG2_DEFROST_EVAP_DIFF_2  = 8   # P15: env vs evaporator-coil temp diff 2 [°C]
PG2_DEFROST_AMB_TEMP     = 9   # P16: ambient temp for defrosting [°C]
# Indices 10..19 still unmapped. Best guess: pg2[10] = F08 (minimum DC
# pump speed, manual default 40 — our snapshot has 30, plausibly user
# adjusted). pg2[11..19] would then be unrelated factory parameters not
# documented in the user-accessible System Parameters list.
#
# Type info inferred from a Celsius -> Fahrenheit unit toggle:
#   indices that converted via F = C*9/5+32  ARE temperatures:
#     pg2[4], pg2[6], pg2[7], pg2[8], pg2[9]
#   indices that did NOT change with the unit toggle are NOT temperatures:
#     pg2[2], pg2[3], pg2[5], pg2[10..19]
# So the rising sequence pg2[10..19] = 30,35,40,45,55,60,65,70,75,80 is
# almost certainly something else (pump RPM ladder, frequency, percentage)
# rather than the heating compensation curve we initially guessed.
#
# Type info for the still-unmapped temperature indices in other groups
# (also inferred from the unit toggle):
#   pg3[6]
#   pg4[3], pg4[5..9], pg4[13..16]
#   pg6[1], pg6[10], pg6[16], pg6[17]
#   pg7[1], pg7[5..11], pg7[15]
# pg7[5..11] in particular looks like an e-heater curve (ambient-temp
# breakpoints around the e_heater_mode setting at pg7[14]).

# parameter_group_7 — write path is DPS 124 (extrapolated from pg1=118, pg2=119)
#
# Smart Grid Ready (SG Ready) is a German standard that lets a heat pump
# accept two relay inputs from a smart meter / home energy manager and
# adapt its behaviour to the state of the grid. The full standard defines
# four bit-pair states (00=lock, 01=normal, 10=recommend, 11=force), but
# this firmware only exposes three values 0/1/2 — most likely:
#   0 = SG disabled (heat pump ignores grid relay inputs)
#   1 = SG passive  (state is read but the heat pump does not act on it)
#   2 = SG active   (heat pump shifts heating / DHW behaviour when the
#                    grid signals surplus or shortage)
# Exact semantics of 0/1/2 are not in the manufacturer datasheet we have
# access to, so they should be confirmed empirically before relying on
# them for energy-management automation (e.g. PV surplus boosting).
PG7_SMART_GRID         = 12
PG7_SMART_GRID_OP_TIME = 13   # how long [minutes] the heat pump stays in the SG-triggered mode

# E-heater = the electric backup resistor inside the heat pump. It draws
# 3-9 kW directly from the mains and is only worth running when outdoor
# temps are so low that the heat pump's own COP collapses, when the heat
# pump cannot reach the DHW target on its own, or briefly during a
# defrost cycle. Mode picks which subsystems are allowed to call it:
#   0 = off (never)
#   1 = heating circuit only
#   2 = DHW only
#   3 = heating + DHW (maximum comfort, worst running cost)
PG7_E_HEATER_MODE = 14

HP_E_HEATER_OFF      = 0
HP_E_HEATER_HEATING  = 1
HP_E_HEATER_DHW      = 2
HP_E_HEATER_BOTH     = 3

HP_SMART_GRID_DISABLED = 0
HP_SMART_GRID_PASSIVE  = 1
HP_SMART_GRID_ACTIVE   = 2

HP_DC_PUMP_OFF    = 0
HP_DC_PUMP_AUTO   = 1
HP_DC_PUMP_MANUAL = 2

# PG1_FUNCTION_MODE values (enum, NOT a bitmask), in app order:
#   1 = heating only
#   2 = heating + cooling
#   3 = heating + DHW
#   4 = heating + cooling + DHW
# Cooling-only / DHW-only / cooling+DHW modes are not exposed by the app.
HP_FUNCTION_HEATING_ONLY        = 1
HP_FUNCTION_HEATING_COOLING     = 2
HP_FUNCTION_HEATING_DHW         = 3
HP_FUNCTION_HEATING_COOLING_DHW = 4

# PG1_PUMP_AFTER_TARGET values (F02 in the manual):
#   0 = intermittent (cycle on/off, period set by PG1_PUMP_CYCLE_MIN)
#   1 = all time     (pump runs continuously after target reached)
#   2 = stop at constant temp
HP_PUMP_AFTER_INTERMITTENT = 0
HP_PUMP_AFTER_ALL_TIME     = 1
HP_PUMP_AFTER_STOP         = 2
HP_PUMP_AFTER_NONSTOP      = HP_PUMP_AFTER_ALL_TIME  # legacy alias

# PG1_FREQ_AFTER_TARGET values:
#   0 = reduced (compressor slows down)
#   1 = fixed   (compressor stays at fixed frequency)
HP_FREQ_AFTER_REDUCED = 0
HP_FREQ_AFTER_FIXED   = 1

# Setpoint ranges from the manufacturer manual (P-code in the comment).
# Outside these the change is rejected up-front so a typo cannot drive
# the heat pump into an unsafe / nonsensical state.
RANGE_COOLING_RETURN_DIFF   = (2, 18)     # P01
RANGE_DHW_RETURN_DIFF       = (2, 18)     # P02
RANGE_DHW_TARGET_TEMP       = (28, 60)    # P03
RANGE_COOLING_TARGET_TEMP   = (7, 30)     # P04
RANGE_HEATING_TARGET_TEMP   = (15, 50)    # P05
RANGE_WATER_TEMP_COMP       = (-5, 15)    # P08
RANGE_DISINFECT_CYCLE_DAYS  = (0, 30)     # P17
RANGE_DISINFECT_START_HOUR  = (0, 23)     # P18
RANGE_DISINFECT_SUSTAIN_MIN = (0, 90)     # P19
RANGE_DISINFECT_TARGET_TEMP = (0, 90)     # P20
RANGE_DISINFECT_HP_TEMP     = (40, 60)    # P21
RANGE_HEATING_COMP_AMB_TEMP = (0, 40)     # P23
RANGE_TARGET_TEMP_COMP_COEF = (1, 30)     # P24 (unit = 0.1)
RANGE_PIPE_HEATER_AMB_TEMP  = (-20, 20)   # P26
RANGE_DHW_HEATER_START_TIME = (0, 60)     # P27
RANGE_PUMP_CYCLE_MIN        = (1, 120)    # F03
RANGE_DC_PUMP_MANUAL_SPEED  = (10, 100)   # F06
RANGE_DEFROST_FREQ          = (30, 120)   # P09
RANGE_DEFROST_PERIOD        = (20, 90)    # P10
RANGE_DEFROST_ENTER_TEMP    = (-15, -1)   # P11
RANGE_DEFROST_TIME          = (5, 20)     # P12
RANGE_DEFROST_EXIT_TEMP     = (1, 40)     # P13
RANGE_DEFROST_EVAP_DIFF     = (0, 15)     # P14, P15
RANGE_DEFROST_AMB_TEMP      = (0, 20)     # P16
RANGE_SMART_GRID_OP_TIME    = (0, 720)    # (factory param, range unconfirmed)

# Legacy alias
RANGE_HEATING_RETURN_DIFF = RANGE_COOLING_RETURN_DIFF


def _hpDps():
    """Return Tuya DPS dict for the heat pump (or None on failure)."""
    return hpTuya.status().get("dps", None)


_HP_STATUS_TTL_SEC = 30   # how long a cloud read stays fresh
_hp_status_cache = {"ts": 0.0, "groups": {}}   # {group_idx: [int32 x 20]}


def _hpStatusCacheStore(HP):
    """Decode all parameter_group_* base64 blobs out of the raw cloud
    payload and stash them in the in-process cache."""
    import base64, struct, time
    groups = {}
    for it in HP:
        code = it.get("code", "") if isinstance(it, dict) else ""
        if code.startswith("parameter_group_"):
            try:
                idx = int(code.rsplit("_", 1)[1])
                groups[idx] = list(struct.unpack(
                    ">%di" % PARAM_GROUP_INTS,
                    base64.b64decode(it["value"])))
            except Exception:
                pass
    _hp_status_cache["ts"] = time.time()
    _hp_status_cache["groups"] = groups


def _hpStatusCacheGet(group_idx):
    import time
    if time.time() - _hp_status_cache["ts"] > _HP_STATUS_TTL_SEC:
        return None
    return _hp_status_cache["groups"].get(group_idx)


def _hpStatusCacheUpdate(group_idx, ints):
    """After a successful local write, store the new values in the cache
    so the next read sees them without going back to the cloud."""
    _hp_status_cache["groups"][group_idx] = list(ints)


def _hpStatusCacheClear():
    _hp_status_cache["ts"] = 0.0
    _hp_status_cache["groups"] = {}


def _pgRead(group_idx, force=False):
    """Return parameter_group_<group_idx> as 20 int32 values. group_idx
    is 1..7. Required because the local tunnel does not expose these
    DPs in status() reads. Cached for _HP_STATUS_TTL_SEC seconds —
    pass force=True to bypass the cache."""
    if not force:
        cached = _hpStatusCacheGet(group_idx)
        if cached is not None:
            return list(cached)

    if not heatpump_refreshStatus().get("ok"):
        return None
    cached = _hpStatusCacheGet(group_idx)
    return list(cached) if cached is not None else None


def _pgWrite(group_idx, ints):
    """Encode 20 int32 values and write them to parameter_group_<group_idx>
    via the local Tuya tunnel. The DPS code is 117 + group_idx
    (verified for pg1 and pg2; pg3..7 follow the same convention).
    Updates the in-process cache so the next read sees the new values
    without going back to the cloud."""
    import base64, struct
    if len(ints) != PARAM_GROUP_INTS:
        raise ValueError("parameter_group_%d must be %d ints, got %d" %
                         (group_idx, PARAM_GROUP_INTS, len(ints)))
    b64 = base64.b64encode(struct.pack(">%di" % PARAM_GROUP_INTS, *ints)).decode()
    res = hpTuya.set_value(117 + group_idx, b64)
    _hpStatusCacheUpdate(group_idx, ints)
    return res


# Back-compat aliases for the original pg1-only helpers
def _pg1Read():
    return _pgRead(1)


def _pg1Write(ints):
    return _pgWrite(1, ints)


def _resolveSetpoint(current, kwargs, value_range):
    """Compute the new int value for a setpoint.

    Accepts either kwargs['direction'] in ('up','down') for a +/-1 nudge,
    or kwargs['value'] for an absolute set. Returns the new value clamped
    to value_range, or None if the request is invalid."""
    direction = kwargs.get("direction")
    value = kwargs.get("value")
    if value is not None:
        try:
            new = int(value)
        except (TypeError, ValueError):
            return None
    elif direction == "up":
        new = current + 1
    elif direction == "down":
        new = current - 1
    else:
        return None
    lo, hi = value_range
    if new < lo or new > hi:
        log.warning("setpoint %s out of range %s..%s, rejected" % (new, lo, hi))
        return None
    return new


def _setPgSetpoint(group, index, kwargs, value_range, label):
    """Read parameter_group_<group>, mutate one int32 by index, write back.
    Returns {value: new, ok: bool}."""
    ints = _pgRead(group)
    if ints is None:
        return {"ok": False, "msg": "could not read parameter_group_%d" % group}
    new = _resolveSetpoint(ints[index], kwargs, value_range)
    if new is None:
        return {"ok": False, "msg": "invalid or out-of-range request"}
    if new == ints[index]:
        return {"ok": True, "value": new, "unchanged": True}
    ints[index] = new
    _pgWrite(group, ints)
    log.info("heat pump %s -> %s" % (label, new))
    return {"ok": True, "value": new}


def _setPg1Setpoint(index, kwargs, value_range, label):
    return _setPgSetpoint(1, index, kwargs, value_range, label)


_hp_cloud_client = None


def _hpCloud():
    """Return a (cached) tinytuya.Cloud client. Building the client
    fetches an auth token from the Tuya cloud, which costs ~5 s; we
    keep the instance around so every subsequent call reuses the
    cached token until it expires."""
    global _hp_cloud_client
    if _hp_cloud_client is None:
        auth = conf.Tuya.auth
        _hp_cloud_client = tinytuya.Cloud(
            apiRegion=auth.get("apiRegion", "eu"),
            apiKey=auth["apiKey"],
            apiSecret=auth["apiSecret"],
        )
    return _hp_cloud_client


def heatpump_settingsLoad(**kwargs):
    """Return all parameter_group_* arrays as 20-int lists for the
    settings UI. Uses the in-process cache when fresh — pass force=1
    to force a cloud refresh."""
    import time
    force = bool(kwargs.get("force"))
    fresh = (time.time() - _hp_status_cache["ts"]) <= _HP_STATUS_TTL_SEC
    if force or not fresh:
        if not heatpump_refreshStatus().get("ok"):
            return {"ok": False, "msg": "cloud read failed"}
    result = {"ok": True}
    for idx, ints in _hp_status_cache["groups"].items():
        result["parameter_group_%d" % idx] = list(ints)
    return result


def heatpump_refreshStatus(**kwargs):
    """Pull a fresh parameter_group_* snapshot from the Tuya cloud and cache
    it under the 'heatpump_status' redis key plus the in-process pg cache.
    Returns {ok: bool, msg: str}. Used because the local Tuya tunnel does
    not expose DPS 118."""
    api = _hpCloud()
    res = api.getstatus(HP_DEVICE_ID)
    payload = res.get("result") if isinstance(res, dict) else None
    if not payload or not res.get("success", False):
        msg = res.get("msg", "unknown error") if isinstance(res, dict) else "no response"
        log.error("heatpump_refreshStatus: %s" % msg)
        return {"ok": False, "msg": msg}

    conf.db.conn.set("heatpump_status", pickle.dumps(payload))
    _hpStatusCacheStore(payload)
    codes = sorted([item.get("code") for item in payload if isinstance(item, dict)])
    log.info("heatpump_refreshStatus: cached %d codes" % len(codes))
    return {"ok": True, "codes": codes}


def getPort(id):
    return conf.Lights.ports[conf.Lights.ids.index(id)]


def lights_switch(**kwargs):
    id        = kwargs.get("id", None)
    direction = kwargs.get("direction", None)
    type = kwargs.get("type", None)

    if type == "relay":
        if (conf.Lights.httpConn == 1):
            item = conf.Lights.items[id]
            url = "/?p=%s&v=%s" % (item["port"], 1 if direction == "on" else 0)
            data = sendReq(item["ip"], url)
   
    data = dict()
    #log.info("id: %s, d: %s, type: %s" % (id, direction, type))
    if type == "tuya":

        device = conf.Tuya.devices[id]
        #print (device)
        if device["name"]:
            d = tinytuya.OutletDevice(dev_id=device["id"], address=device["ip"], local_key=device["key"], version=device["ver"])
            if direction == "on":
                d.turn_on()
            else:
                d.turn_off()
                    
            status = d.status()
            data["status"] = status["dps"]["1"]


    data["id"]  = id
    data["direction"] = direction
    data["type"] = type

    return data


def heating_SensorRefresh(**kwargs):
    db = conf.db.conn

    data = dict()
    manifold = utils.toStr(db.get("heating_manifold_state"))#[::-1]
    #mapSensorsToManifold = {10178502:[1,2], 10243897:[7], 10202255:[8], 10200594:[3], 10204017:[4]}
    #log.info("Manifold: %s" % manifold)

    for item in db.keys("temp_sensor_*"):
        sensor = pickle.loads(db.get(item))
        sensorId = sensor.get("sensorId", None)
            

        confData = conf.HeatingSensors.items.get(sensorId, None)
        if confData is not None:
            data[confData] = sensor
        else:
            #log.warn("SensorId: %s is not in config.ini" % sensorId)
            continue

        for p in conf.HeatingSensors.mapSensorsToManifold.get(sensor["sensorId"]):
            #log.info("p >>> %s : %s" % (sensor["sensorId"], manifold[p]))
            if manifold[p] == '1':
                data[conf.HeatingSensors.items[sensor["sensorId"]]]["status"] = 1
                break
            else:
                data[conf.HeatingSensors.items[sensor["sensorId"]]]["status"] = 0

    data["heating_state"] = utils.toInt(db.get("heating_state"))
    data["heating_direction"] = utils.toStr(db.get("heating_direction"))
    data["heating_time"] = utils.toInt(db.get("heating_time"))

    return data

"""
def blinds(**kwargs):

    db = conf.db.conn

    id = kwargs.get("id", "")
    direction = kwargs.get("direction", None)

    items = db.get("blinds")
    if items is not None:
        items = pickle.loads(items)
    else:
        items = dict()

    item = items.get(id, dict())
    item["direction"] = direction
    if direction in ('up', 'down'):
        item["counter_%s" % direction] = item.get("counter_%s" % direction, 0) + 1
    items[id] = item

    db.set("blinds", pickle.dumps(items))
    
    #log.info("item %s" % item)
    #log.info("blinds <%s>" % items)

    return {
        "direction" : direction,
        "id" : id}
"""

def heating_switch(**kwargs):

    db = conf.db.conn
    direction = utils.toStr(db.get("heating_direction"))

    if direction == "heating":
        d = "cooling"
        db.set("heating_direction", d)
    else:
        d = "heating"
        db.set("heating_direction", d)

    return {
        "direction" : d}


def heating(**kwargs):

    db = conf.db.conn

    id = kwargs.get("id", "")
    direction = kwargs.get("direction", None)
    roomId = "heating_" + id

    room = db.get(roomId)
    if room is not None:
        room = pickle.loads(room)
        temperature = room.get("temperature")
    else:
        room = dict()
        room["temperature"] = conf.Heating.minimalTemperature
        room["id"] = id

        db.set(roomId, pickle.dumps(room))

        room["temperature"] = "%.1f" % conf.Heating.minimalTemperature
        return room

    #setTempereature(temperature, direction)
    #print (conf.port)
    if direction == "up":
        temperature = temperature + .25

    elif direction == "down":
        temperature = temperature - .25

    if temperature < conf.Heating.minimalTemperature:
        temperature =  conf.Heating.minimalTemperature
    elif temperature > conf.Heating.maximalTemperature:
        temperature = conf.Heating.minimalTemperature

    room["temperature"] = temperature
    db.set(roomId, pickle.dumps(room))

    temperature = "%.1f" % temperature


    return {
        "temperature" : temperature,
        "id" : id}


class Key(dict):

    def __lt__(item0, item1):

        a1, a2 = item0["value"].split(":")
        b1, b2 = item1["value"].split(":")

        mina = a1 * 60 + a2
        minb = b1 * 60 + b2

        return (mina < minb)


def heating_load(**kwargs):

    db = conf.db.conn

    roomId = kwargs.get("roomId", "")

    data = db.get("heating_values_" + roomId)
    if data:
        items = pickle.loads(data)
    else:
        items = list()
    return {
        "items" : items,
        "roomId" : roomId
    }


def heating_add(**kwargs):

    db = conf.db.conn
    item = dict()

    roomId = kwargs.get("roomId", "")
    item["value"] = kwargs.get("value", "")
    item["temperature"] = "%.1f" % 20.0

    items = db.get("heating_values_" + roomId)
    if items:
        items = pickle.loads(items)
    else:
        items = list()

    items.append(item)
    items = sorted(items, key=Key)
    db.set("heating_values_" + roomId, pickle.dumps(items))

    return {
        "items" : items,
        "roomId" : roomId
    }


def heating_setTemp(**kwargs):

    db = conf.db.conn

    roomId = kwargs.get("roomId", "")
    index = kwargs.get("index", "")
    direction = kwargs.get("direction", "")
    log.info("roo:%s i:%s d:%s" % (roomId, index, direction) )
    items = db.get("heating_values_" + roomId)
    if items:
        items = pickle.loads(items)
        item = items.pop(index)

    log.info("items: %s" % (items) )


    if direction == "up":
        item["temperature"] = float(item["temperature"]) + .25

    elif direction == "down":
        item["temperature"] = float(item["temperature"]) - .25

    if item["temperature"] < conf.Heating.minimalTemperature:
        item["temperature"] =  conf.Heating.minimalTemperature
    elif item["temperature"] > conf.Heating.maximalTemperature:
        item["temperature"] = conf.Heating.minimalTemperature

    item["temperature"] = "%.1f" % item["temperature"]
    items.append(item)
    items = sorted(items, key=Key)
    db.set("heating_values_" + roomId, pickle.dumps(items))

    return {
        "items" : items,
        "roomId" : roomId
    }


def heating_delete(**kwargs):

    db = conf.db.conn

    roomId = kwargs.get("roomId", "")
    index = kwargs.get("index", "")

    data = db.get("heating_values_" + roomId)
    if data:
        items = pickle.loads(data)
    else:
        items = list()

    items.pop(index)
    db.set("heating_values_" + roomId, pickle.dumps(items))
    log.info(items)

    return {
        "items" : items,
        "index" : index
    }


def invertor_load(**kwargs):

    db = conf.db.conn

    i1 = db.get("invertor_1")
    i2 = db.get("invertor_2")
    if i1:
        data1 = pickle.loads(i1)
        data2 = pickle.loads(i2)
        data1["outputPowerActive"] = data1["outputPowerActive"] + data2["outputPowerActive"]
        data1["outputPowerApparent"] = data1["outputPowerApparent"] + data2["outputPowerApparent"]
        data1["batteryCurrent"] = data1["batteryCurrent"] + data2["batteryCurrent"]
        data1["batteryDischargeCurrent"] = data1["batteryDischargeCurrent"] + data2["batteryDischargeCurrent"]
        data1["solarCurrent2"] = data2["solarCurrent"]
        data1["solarVoltage2"] = data2["solarVoltage"]
        #log.info("Data 1: %s" % data1)
        #log.info("Data 2: %s" % data2)

    else:
        data1 = dict()
    return {
        "data" : data1
    }


def heatpump_setOnOff(**kwargs):
    data = _hpDps()
    new_state = not data.get(str(DPS_POWER), False)
    hpTuya.set_value(DPS_POWER, new_state)
    data[str(DPS_POWER)] = new_state
    log.info("Switch HP: %s" % new_state)
    return {"hpTuyaData": data}


# smart, mute, strong
def heatpump_setMode(**kwargs):
    mode = kwargs.get("mode")
    if mode not in ("smart", "mute", "strong"):
        return {}

    hpTuya.set_value(DPS_MODE, mode)
    data = _hpDps()
    log.info("TT mode : %s" % data)
    return {"hpTuyaData": data}


# heat, cool (wth, wth_heat, wth_cool not supported here yet)
def heatpump_setWorkMode(**kwargs):
    mode = kwargs.get("mode")
    if mode not in ("cool", "heat"):
        return {}

    hpTuya.set_value(DPS_WORK_MODE, mode)
    data = _hpDps()
    conf.db.conn.set("heating_direction", "cooling" if mode == "cool" else "heating")
    log.info("TT mode : %s" % data)
    return {"hpTuyaData": data}


def heatpump_status(**kwargs):
    return {"hpTuyaData": _hpDps()}


def heatpump_setTemp(**kwargs):
    """Set heating target water temperature. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_HEATING_TARGET_TEMP, kwargs, RANGE_HEATING_TARGET_TEMP, "heating_target_temp")
    if res.get("ok"):
        conf.db.conn.set("heatpump_status_heating_target_water_temp", res["value"])
    return {"temperature": res.get("value")} if res.get("ok") else {}


def heatpump_setCoolingTemp(**kwargs):
    """Set cooling target water temperature. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_COOLING_TARGET_TEMP, kwargs, RANGE_COOLING_TARGET_TEMP, "cooling_target_temp")
    return {"temperature": res.get("value")} if res.get("ok") else {}


def heatpump_setDHWTemp(**kwargs):
    """Set DHW (domestic hot water) target temperature. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_DHW_TARGET_TEMP, kwargs, RANGE_DHW_TARGET_TEMP, "dhw_target_temp")
    return {"temperature": res.get("value")} if res.get("ok") else {}


def heatpump_setCoolingReturnDifference(**kwargs):
    """Set the temperature differential between return water and cooling
    target temp (manual code P01). kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_COOLING_RETURN_DIFF, kwargs, RANGE_COOLING_RETURN_DIFF, "cooling_return_diff")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setReturnDifference(**kwargs):
    """Legacy alias for heatpump_setCoolingReturnDifference. The original
    label "heating return diff" was wrong — manual confirms P01 is for
    the cooling target."""
    return heatpump_setCoolingReturnDifference(**kwargs)


def heatpump_setDHWReturnDifference(**kwargs):
    """Set DHW return-water differential. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_DHW_RETURN_DIFF, kwargs, RANGE_DHW_RETURN_DIFF, "dhw_return_diff")
    return {"value": res.get("value")} if res.get("ok") else {}


def _setPgEnum(group, index, kwargs, allowed, label):
    """Generic enum setter for parameter_group_<group> indices that hold
    a discrete code rather than a temperature."""
    val = kwargs.get("value")
    try:
        val = int(val)
    except (TypeError, ValueError):
        return {}
    if val not in allowed:
        log.warning("heat pump %s: rejected value %s (allowed: %s)" % (label, val, sorted(allowed)))
        return {}
    ints = _pgRead(group)
    if ints is None:
        return {}
    if ints[index] == val:
        return {"value": val, "unchanged": True}
    ints[index] = val
    _pgWrite(group, ints)
    log.info("heat pump %s -> %s" % (label, val))
    return {"value": val}


def _setPg1Enum(index, kwargs, allowed, label):
    return _setPgEnum(1, index, kwargs, allowed, label)


def heatpump_setFunction(**kwargs):
    """Set the heat pump function (which subsystems are active). kwargs: value=N
    (1=heating, 2=heating+cooling, 3=heating+DHW, 4=heating+cooling+DHW)."""
    return _setPg1Enum(PG1_FUNCTION_MODE, kwargs,
                       {HP_FUNCTION_HEATING_ONLY, HP_FUNCTION_HEATING_COOLING,
                        HP_FUNCTION_HEATING_DHW, HP_FUNCTION_HEATING_COOLING_DHW},
                       "function_mode")


def heatpump_setPumpAfterTarget(**kwargs):
    """Set water-pump behaviour after target temperature is reached
    (manual code F02). kwargs: value=0 (intermittent), 1 (all time) or
    2 (stop at constant temp)."""
    return _setPg1Enum(PG1_PUMP_AFTER_TARGET, kwargs,
                       {HP_PUMP_AFTER_INTERMITTENT, HP_PUMP_AFTER_ALL_TIME, HP_PUMP_AFTER_STOP},
                       "pump_after_target")


def heatpump_setPumpCycleMin(**kwargs):
    """Set the circulation-pump on/off cycle length (minutes), used when
    pump_after_target is set to intermittent. kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_PUMP_CYCLE_MIN, kwargs, RANGE_PUMP_CYCLE_MIN, "pump_cycle_min")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setPipeHeaterAmbTemp(**kwargs):
    """Set the ambient-temperature threshold below which the pipe heater
    (anti-freeze) starts. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_PIPE_HEATER_AMB_TEMP, kwargs, RANGE_PIPE_HEATER_AMB_TEMP, "pipe_heater_amb_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setFreqAfterConstTemp(**kwargs):
    """Set compressor frequency mode after a constant water temperature
    has been reached (manual code P25). kwargs: value=0 (decrease) or
    value=1 (non-decrease)."""
    return _setPg1Enum(PG1_FREQ_AFTER_CONST_TEMP, kwargs,
                       {HP_FREQ_AFTER_REDUCED, HP_FREQ_AFTER_FIXED},
                       "freq_after_const_temp")


def heatpump_setFreqAfterTarget(**kwargs):
    """Legacy alias for heatpump_setFreqAfterConstTemp."""
    return heatpump_setFreqAfterConstTemp(**kwargs)


def heatpump_setWaterTempComp(**kwargs):
    """Set water-temperature compensation offset (°C). Compensates for
    sensor placement so the displayed/target temp matches the actual
    delivered water temp. kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_WATER_TEMP_COMP, kwargs, RANGE_WATER_TEMP_COMP, "water_temp_comp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDisinfectCycleDays(**kwargs):
    """Set the legionella disinfection cycle interval (days). 0 disables
    the high-temperature disinfection program. kwargs: direction=up|down
    or value=N."""
    res = _setPg1Setpoint(PG1_DISINFECT_CYCLE_DAYS, kwargs, RANGE_DISINFECT_CYCLE_DAYS, "disinfect_cycle_days")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDisinfectStartHour(**kwargs):
    """Set the hour of day (0..23) at which the legionella disinfection
    program runs. kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_DISINFECT_START_HOUR, kwargs, RANGE_DISINFECT_START_HOUR, "disinfect_start_hour")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDisinfectSustainMin(**kwargs):
    """Set how long (minutes) the legionella disinfection program holds
    the high temperature. kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_DISINFECT_SUSTAIN_MIN, kwargs, RANGE_DISINFECT_SUSTAIN_MIN, "disinfect_sustain_min")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDisinfectTargetTemp(**kwargs):
    """Set the target temperature (°C) of the legionella disinfection
    program. kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_DISINFECT_TARGET_TEMP, kwargs, RANGE_DISINFECT_TARGET_TEMP, "disinfect_target_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDisinfectHpTemp(**kwargs):
    """Set the heat-pump output setpoint (°C) used during the disinfection
    program (the value the heat pump itself drives toward, separate from
    the tank target). kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_DISINFECT_HP_TEMP, kwargs, RANGE_DISINFECT_HP_TEMP, "disinfect_hp_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setHeatingAutoAdjust(**kwargs):
    """Enable or disable automatic adjustment of the heating target
    temperature (typically based on outdoor temperature / weather).
    kwargs: value=0 (disabled) or value=1 (enabled)."""
    return _setPg1Enum(PG1_HEATING_AUTO_ADJUST, kwargs, {0, 1}, "heating_auto_adjust")


def heatpump_setHeatingCompAmbTemp(**kwargs):
    """Set the reference ambient temperature used by the heating
    compensation curve. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_HEATING_COMP_AMB_TEMP, kwargs, RANGE_HEATING_COMP_AMB_TEMP, "heating_comp_amb_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setTargetTempCompCoef(**kwargs):
    """Set the target temperature compensation coefficient (slope of
    the compensation curve). kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_TARGET_TEMP_COMP_COEF, kwargs, RANGE_TARGET_TEMP_COMP_COEF, "target_temp_comp_coef")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDhwHeaterStartTime(**kwargs):
    """Set the delay (minutes) before the DHW backup electric heater
    starts when the heat pump can't reach DHW target on its own.
    kwargs: direction=up|down or value=N."""
    res = _setPg1Setpoint(PG1_DHW_HEATER_START_TIME, kwargs, RANGE_DHW_HEATER_START_TIME, "dhw_heater_start_time")
    return {"value": res.get("value")} if res.get("ok") else {}


# --- parameter_group_2 setters ---

def heatpump_setDcPumpMode(**kwargs):
    """Set the DC circulation pump mode.
    kwargs: value=0 (off), value=1 (automatic) or value=2 (manual)."""
    return _setPgEnum(2, PG2_DC_PUMP_MODE, kwargs,
                      {HP_DC_PUMP_OFF, HP_DC_PUMP_AUTO, HP_DC_PUMP_MANUAL},
                      "dc_pump_mode")


def heatpump_setDcPumpManualSpeed(**kwargs):
    """Set the DC water-pump speed in percent, used when DC pump mode is
    manual. kwargs: direction=up|down or value=N."""
    res = _setPgSetpoint(2, PG2_DC_PUMP_MANUAL_SPEED, kwargs,
                         RANGE_DC_PUMP_MANUAL_SPEED, "dc_pump_manual_speed")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostFreq(**kwargs):
    """Set compressor frequency (Hz) during a defrost cycle. Higher
    frequency clears ice faster but uses more power."""
    res = _setPgSetpoint(2, PG2_DEFROST_FREQ, kwargs, RANGE_DEFROST_FREQ, "defrost_freq")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostPeriod(**kwargs):
    """Set the minimum interval between defrost cycles (minutes). Too
    low wastes energy, too high lets ice build up on the evaporator."""
    res = _setPgSetpoint(2, PG2_DEFROST_PERIOD, kwargs, RANGE_DEFROST_PERIOD, "defrost_period")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostEnterTemp(**kwargs):
    """Set the ambient-temperature threshold (°C) below which defrost
    cycles are allowed. Above this temperature ice does not form on
    the outdoor coil so defrost is suppressed."""
    res = _setPgSetpoint(2, PG2_DEFROST_ENTER_TEMP, kwargs, RANGE_DEFROST_ENTER_TEMP, "defrost_enter_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostTime(**kwargs):
    """Set the maximum duration of a single defrost cycle (minutes).
    Acts as a safety cap if the cycle's normal exit conditions fail."""
    res = _setPgSetpoint(2, PG2_DEFROST_TIME, kwargs, RANGE_DEFROST_TIME, "defrost_time")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostExitTemp(**kwargs):
    """Set the evaporator-coil temperature (°C) at which a defrost cycle
    ends — the cycle stops once the coil warms back up to this value,
    indicating the ice has melted."""
    res = _setPgSetpoint(2, PG2_DEFROST_EXIT_TEMP, kwargs, RANGE_DEFROST_EXIT_TEMP, "defrost_exit_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostEvapDiff1(**kwargs):
    """Set the first ambient-vs-evaporator temperature delta (°C) used
    to detect frost build-up. A coil colder than ambient by this much
    is the early warning threshold."""
    res = _setPgSetpoint(2, PG2_DEFROST_EVAP_DIFF_1, kwargs, RANGE_DEFROST_EVAP_DIFF, "defrost_evap_diff_1")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostEvapDiff2(**kwargs):
    """Set the second ambient-vs-evaporator temperature delta (°C) — the
    firm threshold that actually triggers a defrost cycle."""
    res = _setPgSetpoint(2, PG2_DEFROST_EVAP_DIFF_2, kwargs, RANGE_DEFROST_EVAP_DIFF, "defrost_evap_diff_2")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDefrostAmbTemp(**kwargs):
    """Set the maximum ambient temperature (°C) above which no defrost
    cycle will be initiated (no ice can form on the outdoor coil)."""
    res = _setPgSetpoint(2, PG2_DEFROST_AMB_TEMP, kwargs, RANGE_DEFROST_AMB_TEMP, "defrost_amb_temp")
    return {"value": res.get("value")} if res.get("ok") else {}


# --- parameter_group_7 setters ---

def heatpump_setSmartGrid(**kwargs):
    """Set the Smart Grid Ready capability mode.
    kwargs: value=0 (disabled), value=1 (passive) or value=2 (active).
    See the comment on PG7_SMART_GRID for what each mode is supposed
    to do."""
    return _setPgEnum(7, PG7_SMART_GRID, kwargs,
                      {HP_SMART_GRID_DISABLED, HP_SMART_GRID_PASSIVE, HP_SMART_GRID_ACTIVE},
                      "smart_grid")


def heatpump_setSmartGridOpTime(**kwargs):
    """Set how long (minutes) the heat pump stays in the SG-triggered
    mode after a grid signal is received. kwargs: direction=up|down or value=N."""
    res = _setPgSetpoint(7, PG7_SMART_GRID_OP_TIME, kwargs,
                         RANGE_SMART_GRID_OP_TIME, "smart_grid_op_time")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setEHeaterMode(**kwargs):
    """Pick which subsystems are allowed to engage the electric backup
    heater. kwargs: value=0 (off), 1 (heating only), 2 (DHW only) or
    3 (both). See PG7_E_HEATER_MODE for cost / comfort trade-offs."""
    return _setPgEnum(7, PG7_E_HEATER_MODE, kwargs,
                      {HP_E_HEATER_OFF, HP_E_HEATER_HEATING,
                       HP_E_HEATER_DHW, HP_E_HEATER_BOTH},
                      "e_heater_mode")


def heatpump_hourlyCharts():
    client = conf.Influx.getHpClient()

    res = client.query("""
        SELECT
            mean(ambientTemperature) as ambientTemperature

        FROM hp WHERE time > now() - 24h group by time(1h) order by time desc limit 24
    """)
    df = pd.DataFrame(res.get_points())
    dfT = df[['time', 'ambientTemperature']]
    dfT.rename(columns={'time': 'x', 'ambientTemperature': 'y'}, inplace=True)

    return {
        "data1" : json.loads(dfT.to_json(orient="records", date_format="iso"))
    }


def heatpump_chartLoad(**kwargs):
    client = conf.Influx.getHpClient()
    
    res = client.query("""
        SELECT
            mean(ambientTemperature) as ambientTemperature

        FROM hp WHERE time > now() - 30d group by time(1d) order by time desc limit 30
    """)
    dfDays = pd.DataFrame(res.get_points())

    dfAT = dfDays[['time', 'ambientTemperature']]
    dfAT.rename(columns={'time': 'x', 'ambientTemperature': 'y'}, inplace=True)
    
    res = client.query("""
        SELECT
            mean(power) as power,
            mean(waterInletTemperature) as waterInletTemperature,
            mean(waterOutletTemperature) as waterOutletTemperature

        FROM hp WHERE time > now() - 48h group by time(1h) order by time desc limit 48
    """)
    df = pd.DataFrame(res.get_points())

    df2 = df[['time', 'power']]
    df2.rename(columns={'time': 'x', 'power': 'y'}, inplace=True)
    
    df3 = df[['time', 'waterInletTemperature']]
    df3.rename(columns={'time': 'x', 'waterInletTemperature': 'y'}, inplace=True)
    
    df4 = df[['time', 'waterOutletTemperature']]
    df4.rename(columns={'time': 'x', 'waterOutletTemperature': 'y'}, inplace=True)
   
    # Pull the current heating target temp directly from parameter_group_1.
    # Cached as a side-effect so heatpump_setTemp can give an instant
    # optimistic update without re-reading the cloud.
    pg1 = _pg1Read()
    heatingTargetWaterTemp = pg1[PG1_HEATING_TARGET_TEMP] if pg1 else None
    if heatingTargetWaterTemp is not None:
        conf.db.conn.set("heatpump_status_heating_target_water_temp", heatingTargetWaterTemp)

    hpTuyaData = hpTuya.status()

    return {
        "hpTuyaData" : hpTuyaData.get("dps", None),
        "heatingTargetWaterTemp" : heatingTargetWaterTemp,
        "data1" : json.loads(dfAT.to_json(orient="records", date_format="iso")),
        "data2" : json.loads(df2.to_json(orient="records", date_format="iso")),
        "data3" : json.loads(df3.to_json(orient="records", date_format="iso")),
        "data4" : json.loads(df4.to_json(orient="records", date_format="iso"))
    }


# Backward-compatible aliases for legacy frontend method names
headpump_hourlyCharts = heatpump_hourlyCharts
chart_heat_pump_load = heatpump_chartLoad


