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
# 20 big-endian int32 values each. Index meanings still need to be reverse
# engineered (use heatpump/dump_params.py to diff snapshots before / after a
# change in the Tuya app). The DP is only readable through the Tuya cloud
# API — the local Tuya tunnel does not expose it.
PARAM_GROUP_INTS  = 20
PARAM_GROUP_BYTES = PARAM_GROUP_INTS * 4

# Legacy bit-position constants, retained while heatpump_setTemp is being
# rewritten against the real int32 layout. Do not rely on them yet.
PARAM_BITS_TOTAL           = 640
PARAM_FIELD_WIDTH          = 6
OFFSET_HEATING_TARGET_TEMP = 480
OFFSET_COOLING_TARGET_TEMP = 512
OFFSET_DHW_TARGET_TEMP     = 544
OFFSET_DHW_RETURN_DIFF     = 576
OFFSET_RETURN_DIFF         = 608


def _hpDps():
    """Return Tuya DPS dict for the heat pump (or None on failure)."""
    return hpTuya.status().get("dps", None)


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


# 608 - return difference for heating and cooling
def heatpump_setReturnDifference(**kwargs):
    mask = (1 << 6) - 1
    mask <<= 608

# 576 - return water and target DWH water temp difference
# DHW - Domestic Hot Water
def heatpump_setDHWReturnDifference(**kwargs):
    mask = (1 << 6) - 1
    mask <<= 576

# 544 - DHW water temp
def heatpump_setDHWTemp(**kwargs):
    mask = (1 << 6) - 1
    mask <<= 544

# 512 - cooling target water temp
def heatpump_setCoolingTemp(**kwargs):
    mask = (1 << 6) - 1
    mask <<= 512

# Heating target water temperature, stored at OFFSET_HEATING_TARGET_TEMP
def heatpump_setTemp(**kwargs):
    direction = kwargs.get("direction")
    if direction not in ("up", "down"):
        return {}

    db = conf.db.conn
    HP = pickle.loads(db.get("heatpump_status"))
    binaryStr = utils.decode64ToBites(utils.getParameterValue(HP, "parameter_group_1"))
    binaryData = int(binaryStr, 2)

    currentTemperature = utils.toInt(db.get("heatpump_status_heating_target_water_temp"))
    targetTemperature = currentTemperature + (1 if direction == "up" else -1)
    log.info("TT current: %s -> target: %s" % (currentTemperature, targetTemperature))

    mask = ((1 << PARAM_FIELD_WIDTH) - 1) << OFFSET_HEATING_TARGET_TEMP
    a = (binaryData & ~mask) | (targetTemperature << OFFSET_HEATING_TARGET_TEMP)
    hp_string = format(a, "0%db" % PARAM_BITS_TOTAL)
    parameter_group_1 = utils.base64encode(utils.stringToBytes(hp_string))

    db.set("heatpump_status_heating_target_water_temp", targetTemperature)
    hpTuya.set_value(DPS_PARAMETER_GROUP_1, parameter_group_1)

    return {"temperature": targetTemperature}


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
   
    #log.info(conf.db.conn.get("heatpump_status_heating_target_water_temp"))
    heatingTargetWaterTemp = conf.db.conn.get("heatpump_status_heating_target_water_temp")
    
    hpTuyaData = hpTuya.status()
    #log.info("DPS : %s", hpTuyaData)

    return {
        "hpTuyaData" : hpTuyaData.get("dps", None),
        "heatingTargetWaterTemp" : json.loads(heatingTargetWaterTemp),
        "data1" : json.loads(dfAT.to_json(orient="records", date_format="iso")),
        "data2" : json.loads(df2.to_json(orient="records", date_format="iso")),
        "data3" : json.loads(df3.to_json(orient="records", date_format="iso")),
        "data4" : json.loads(df4.to_json(orient="records", date_format="iso"))
    }


# Backward-compatible aliases for legacy frontend method names
headpump_hourlyCharts = heatpump_hourlyCharts
chart_heat_pump_load = heatpump_chartLoad


