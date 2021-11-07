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
    print (id)
    if (conf.Lights.httpConn == 1):
        conn = http.client.HTTPConnection(conf.Lights.hwIp, timeout = 5)
        url = "/?p=%s&v=%s" % (getPort(id), 1 if direction == "on" else 0)
        conn.request("GET", url)
        print (conf.Lights.hwIp, url)
        res = conn.getresponse()
        print (res)
        conn.close()
        if res.status == 200:
            resData = res.read()

    log.info("GET http://%s/?p=%s&v=%s Status: <%s>" % (
        conf.Lights.hwIp, getPort(id), 1 if direction == "on" else 0, res.status))

    data = dict()
    data["id"]  = id
    data["direction"] = direction

    return data


def heating_SensorRefresh(**kwargs):
    db = conf.db.conn

    data = dict()
    for item in db.keys("temp_sensor_*"):
        sensor = pickle.loads(db.get(item))
        data[conf.HeatingSensors.items[sensor["sensorId"]]] = sensor

    data["heating_state"] = utils.toInt(db.get("heating_state"))

    return data


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

    #log.error("Temperature: %s %s" % ( temperature, id))

    return {
        "temperature" : temperature,
        "id" : id}
