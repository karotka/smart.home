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


def chart_heat_pump_load(**kwargs):
    client = conf.Influx.getHpClient()
    
    res = client.query("""
        SELECT
            mean(ambientTemperature) as ambientTemperature

        FROM hp group by time(1d) order by time desc limit 30
    """)
    dfDays = pd.DataFrame(res.get_points())

    dfAT = dfDays[['time', 'ambientTemperature']]
    dfAT.rename(columns={'time': 'x', 'ambientTemperature': 'y'}, inplace=True)
    
    res = client.query("""
        SELECT
            mean(power) as power,
            mean(waterInletTemperature) as waterInletTemperature,
            mean(waterOutletTemperature) as waterOutletTemperature

        FROM hp group by time(1h) order by time desc limit 48
    """)
    df = pd.DataFrame(res.get_points())

    df2 = df[['time', 'power']]
    df2.rename(columns={'time': 'x', 'power': 'y'}, inplace=True)
    
    df3 = df[['time', 'waterInletTemperature']]
    df3.rename(columns={'time': 'x', 'waterInletTemperature': 'y'}, inplace=True)
    
    df4 = df[['time', 'waterOutletTemperature']]
    df4.rename(columns={'time': 'x', 'waterOutletTemperature': 'y'}, inplace=True)
    
    return {
        "data1" : json.loads(dfAT.to_json(orient="records", date_format="iso")),
        "data2" : json.loads(df2.to_json(orient="records", date_format="iso")),
        "data3" : json.loads(df3.to_json(orient="records", date_format="iso")),
        "data4" : json.loads(df4.to_json(orient="records", date_format="iso"))
    }




