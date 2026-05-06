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
DPS_CURRENT           = 112  # actual current draw [A]
DPS_PARAMETER_GROUP_1 = 118  # base64-encoded settings blob, cloud-only DP

# parameter_group_1 .. parameter_group_7 are 80-byte base64 blobs containing
# 20 big-endian int32 values each. The DP is only readable through the Tuya
# cloud API (the local tunnel does not expose it in status()), but it IS
# writable through the local tunnel via hpTuya.set_value(118, <base64>).
PARAM_GROUP_INTS  = 20
PARAM_GROUP_BYTES = PARAM_GROUP_INTS * 4

# parameter_group_1 — index meanings, mapped by snapshot diffing the values
# before / after a single change in the Tuya Smart Life app.
PG1_HEATING_RETURN_DIFF = 0
PG1_DHW_RETURN_DIFF     = 1
PG1_DHW_TARGET_TEMP     = 2
PG1_COOLING_TARGET_TEMP = 3
PG1_HEATING_TARGET_TEMP = 4
PG1_WATER_TEMP_COMP      = 5   # water temperature compensation offset [°C]
PG1_DISINFECT_CYCLE_DAYS = 6   # high-temp anti-legionella cycle interval [days] (0 = disabled)
PG1_DISINFECT_START_HOUR = 7   # high-temp anti-legionella program start hour (0..23)
PG1_DISINFECT_SUSTAIN_MIN = 8  # high-temp anti-legionella program sustain time [minutes]
PG1_DISINFECT_TARGET_TEMP = 9  # high-temp anti-legionella program target temperature [°C]
PG1_DISINFECT_HP_TEMP    = 10  # heat-pump output setpoint during disinfection program [°C]
PG1_HEATING_AUTO_ADJUST  = 11  # heating target temp automatic adjustment (0 = disabled, 1 = enabled)
PG1_FREQ_AFTER_TARGET    = 14  # compressor frequency mode after target reached (0 = reduced, 1 = fixed)
PG1_PIPE_HEATER_AMB_TEMP = 15  # ambient temp [°C] below which the pipe heater starts (anti-freeze)
PG1_FUNCTION_MODE       = 17  # operating function selector (heating / cooling / DHW combos)
PG1_PUMP_AFTER_TARGET   = 18  # water-pump behaviour after target temperature reached
PG1_PUMP_CYCLE_MIN      = 19  # circulation-pump on/off cycle length [minutes] (used when intermittent)
# Indices 12, 13, 16 still unmapped.

# parameter_group_2 — index meanings (write API for pg2..7 not yet implemented)
PG2_DC_PUMP_MODE = 0   # 0 = off, 1 = automatic, 2 = manual
# Indices 1..19 still unmapped.

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

# PG1_PUMP_AFTER_TARGET values:
#   0 = on intermittently (cycle on/off)
#   1 = non-stop (always on)
#   2 = stop
HP_PUMP_AFTER_INTERMITTENT = 0
HP_PUMP_AFTER_NONSTOP      = 1
HP_PUMP_AFTER_STOP         = 2

# PG1_FREQ_AFTER_TARGET values:
#   0 = reduced (compressor slows down)
#   1 = fixed   (compressor stays at fixed frequency)
HP_FREQ_AFTER_REDUCED = 0
HP_FREQ_AFTER_FIXED   = 1

# Setpoint ranges (°C). Outside these the change is rejected up-front so a
# typo cannot drive the heat pump into an unsafe / nonsensical state.
RANGE_HEATING_TARGET_TEMP = (25, 65)
RANGE_COOLING_TARGET_TEMP = (7, 25)
RANGE_DHW_TARGET_TEMP     = (25, 60)
RANGE_HEATING_RETURN_DIFF = (1, 15)
RANGE_DHW_RETURN_DIFF     = (1, 15)
RANGE_PUMP_CYCLE_MIN      = (1, 120)
RANGE_PIPE_HEATER_AMB_TEMP = (-20, 20)
RANGE_WATER_TEMP_COMP      = (0, 10)
RANGE_DISINFECT_CYCLE_DAYS = (0, 30)
RANGE_DISINFECT_START_HOUR = (0, 23)
RANGE_DISINFECT_SUSTAIN_MIN = (10, 180)
RANGE_DISINFECT_TARGET_TEMP = (40, 80)
RANGE_DISINFECT_HP_TEMP     = (40, 80)


def _hpDps():
    """Return Tuya DPS dict for the heat pump (or None on failure)."""
    return hpTuya.status().get("dps", None)


def _pg1Read():
    """Refresh the cached parameter_group_1 from the cloud and return its
    20 int32 values. Required because the local tunnel does not expose
    DPS 118 in status() reads."""
    if not heatpump_refreshStatus().get("ok"):
        return None
    HP = pickle.loads(conf.db.conn.get("heatpump_status"))
    pg1_b64 = next((it["value"] for it in HP if it.get("code") == "parameter_group_1"), None)
    if not pg1_b64:
        return None
    import base64, struct
    return list(struct.unpack(">%di" % PARAM_GROUP_INTS, base64.b64decode(pg1_b64)))


def _pg1Write(ints):
    """Encode 20 int32 values and write them to the device via the local
    Tuya tunnel (DPS 118). Returns the raw set_value response."""
    import base64, struct
    if len(ints) != PARAM_GROUP_INTS:
        raise ValueError("parameter_group_1 must be %d ints, got %d" % (PARAM_GROUP_INTS, len(ints)))
    b64 = base64.b64encode(struct.pack(">%di" % PARAM_GROUP_INTS, *ints)).decode()
    return hpTuya.set_value(DPS_PARAMETER_GROUP_1, b64)


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


def _setPg1Setpoint(index, kwargs, value_range, label):
    """Read parameter_group_1, mutate one int32 by index, write back.
    Returns {value: new, ok: bool}."""
    ints = _pg1Read()
    if ints is None:
        return {"ok": False, "msg": "could not read parameter_group_1"}
    new = _resolveSetpoint(ints[index], kwargs, value_range)
    if new is None:
        return {"ok": False, "msg": "invalid or out-of-range request"}
    if new == ints[index]:
        return {"ok": True, "value": new, "unchanged": True}
    ints[index] = new
    _pg1Write(ints)
    log.info("heat pump %s -> %s" % (label, new))
    return {"ok": True, "value": new}


def _hpCloud():
    """Return a tinytuya.Cloud client built from conf.Tuya.auth."""
    auth = conf.Tuya.auth
    return tinytuya.Cloud(
        apiRegion=auth.get("apiRegion", "eu"),
        apiKey=auth["apiKey"],
        apiSecret=auth["apiSecret"],
    )


def heatpump_refreshStatus(**kwargs):
    """Pull a fresh parameter_group_* snapshot from the Tuya cloud and cache
    it under the 'heatpump_status' redis key. Returns {ok: bool, msg: str}.
    Used because the local Tuya tunnel does not expose DPS 118."""
    api = _hpCloud()
    res = api.getstatus(HP_DEVICE_ID)
    payload = res.get("result") if isinstance(res, dict) else None
    if not payload or not res.get("success", False):
        msg = res.get("msg", "unknown error") if isinstance(res, dict) else "no response"
        log.error("heatpump_refreshStatus: %s" % msg)
        return {"ok": False, "msg": msg}

    conf.db.conn.set("heatpump_status", pickle.dumps(payload))
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


def heatpump_setReturnDifference(**kwargs):
    """Set heating return-water differential. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_HEATING_RETURN_DIFF, kwargs, RANGE_HEATING_RETURN_DIFF, "heating_return_diff")
    return {"value": res.get("value")} if res.get("ok") else {}


def heatpump_setDHWReturnDifference(**kwargs):
    """Set DHW return-water differential. kwargs: direction=up|down or value=N (°C)."""
    res = _setPg1Setpoint(PG1_DHW_RETURN_DIFF, kwargs, RANGE_DHW_RETURN_DIFF, "dhw_return_diff")
    return {"value": res.get("value")} if res.get("ok") else {}


def _setPg1Enum(index, kwargs, allowed, label):
    """Generic enum setter for parameter_group_1 indices that hold a
    discrete code rather than a temperature."""
    val = kwargs.get("value")
    try:
        val = int(val)
    except (TypeError, ValueError):
        return {}
    if val not in allowed:
        log.warning("heat pump %s: rejected value %s (allowed: %s)" % (label, val, sorted(allowed)))
        return {}
    ints = _pg1Read()
    if ints is None:
        return {}
    if ints[index] == val:
        return {"value": val, "unchanged": True}
    ints[index] = val
    _pg1Write(ints)
    log.info("heat pump %s -> %s" % (label, val))
    return {"value": val}


def heatpump_setFunction(**kwargs):
    """Set the heat pump function (which subsystems are active). kwargs: value=N
    (1=heating, 2=heating+cooling, 3=heating+DHW, 4=heating+cooling+DHW)."""
    return _setPg1Enum(PG1_FUNCTION_MODE, kwargs,
                       {HP_FUNCTION_HEATING_ONLY, HP_FUNCTION_HEATING_COOLING,
                        HP_FUNCTION_HEATING_DHW, HP_FUNCTION_HEATING_COOLING_DHW},
                       "function_mode")


def heatpump_setPumpAfterTarget(**kwargs):
    """Set water-pump behaviour after target temperature is reached.
    kwargs: value=0 (intermittent), 1 (non-stop) or 2 (stop)."""
    return _setPg1Enum(PG1_PUMP_AFTER_TARGET, kwargs,
                       {HP_PUMP_AFTER_INTERMITTENT, HP_PUMP_AFTER_NONSTOP, HP_PUMP_AFTER_STOP},
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


def heatpump_setFreqAfterTarget(**kwargs):
    """Set compressor frequency mode after target temperature is reached.
    kwargs: value=0 (reduced) or value=1 (fixed)."""
    return _setPg1Enum(PG1_FREQ_AFTER_TARGET, kwargs,
                       {HP_FREQ_AFTER_REDUCED, HP_FREQ_AFTER_FIXED},
                       "freq_after_target")


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


