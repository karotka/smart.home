"""
An entire file for you to expand. Add methods here, and the client should be
able to call them with json-rpc without any editing to the pipeline.
"""
#import RPi.GPIO as gpio

from config import conf
import utils
import pickle
import http.client
import logging

log = logging.getLogger('web')

def getPort(id):
    return conf.Lights.ports[conf.Lights.ids.index(id)]


def lights_switch(**kwargs):
    id        = kwargs.get("id", None)
    direction = kwargs.get("direction", None)
    if (conf.Lights.httpConn == 1):
        conn = http.client.HTTPConnection(conf.Lights.hwIp, timeout = 5)
        url = "/?p=%s&v=%s" % (getPort(id), 1 if direction == "on" else 0)
        conn.request("GET", url)
        res = conn.getresponse()
        resData = res.read()
        conn.close()

    log.info("GET http://%s/?p=%s&v=%s Status: <%s>" % (
        conf.Lights.hwIp, getPort(id), 1 if direction == "on" else 0, res.status))

    data = dict()
    data["id"]  = id
    data["direction"] = direction

    return data


def heating_SensorRefresh(**kwargs):
    db = conf.db.conn

    data = dict()
    manifold = utils.toStr(db.get("heating_manifold_state"))#[::-1]
    #mapSensorsToManifold = {10178502:[1,2], 10243897:[7], 10202255:[8], 10200594:[3], 10204017:[4]}
    #log.info("Manifold: %s" % manifold)

    for item in db.keys("temp_sensor_*"):
        sensor = pickle.loads(db.get(item))
        data[conf.HeatingSensors.items[sensor["sensorId"]]] = sensor
        
        for p in conf.HeatingSensors.mapSensorsToManifold.get(sensor["sensorId"]):
            #log.info("p >>> %s : %s" % (sensor["sensorId"], manifold[p]))
            if manifold[p] == '1':
                data[conf.HeatingSensors.items[sensor["sensorId"]]]["status"] = 1
                break
            else:
                data[conf.HeatingSensors.items[sensor["sensorId"]]]["status"] = 0

    #log.info("Data: %s" % data)
    data["heating_state"] = utils.toInt(db.get("heating_state"))
    data["heating_time"] = utils.toInt(db.get("heating_time"))

    return data


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
        temperature = temperature + .2

    elif direction == "down":
        temperature = temperature - .2

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
        item["temperature"] = float(item["temperature"]) + .2

    elif direction == "down":
        item["temperature"] = float(item["temperature"]) - .2

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
