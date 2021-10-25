"""
An entire file for you to expand. Add methods here, and the client should be
able to call them with json-rpc without any editing to the pipeline.
"""
#import RPi.GPIO as gpio

from config import conf
import utils
import pickle
import http.client


def getPort(id):
    return conf.Lights.ports[conf.Lights.ids.index(id)]


def lights_switch(**kwargs):
    id        = kwargs.get("id", None)
    direction = kwargs.get("direction", None)

    if (conf.Lights.httpConn == 1):
        conn = http.client.HTTPConnection(conf.Lights.hwIp)
        conn.request("GET",
            "/?p=%s&v=%s" % (getPort(id), 1 if direction == "on" else 0))
        res = conn.getresponse()
        if res.status == 200:
            resData = res.read()

    conf.Log.info("GET http://%s/?p=%s&v=%s Status: <%s>" % (
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

import logging
logger = logging.getLogger('web')

def heating(**kwargs):

    db = conf.db.conn

    id = kwargs.get("id", "")
    direction = kwargs.get("direction", None)
    roomId = "heating_" + id

    try:
        room = pickle.loads(db.get(roomId))
        temperature = room.get("temperature")
    except pickle.UnpicklingError as e:
        room = dict()
        room["temperature"] = .0
        temperature = .0

    #print (conf.port)
    if direction == "up":
        temperature = temperature + .2

    elif direction == "down":
        temperature = temperature - .2

    if temperature < conf.Heating.minimalTemperature:
        temperature =  conf.Heating.minimalTemperature

    room["temperature"] = temperature
    db.set(roomId, pickle.dumps(room))

    temperature = "%.1f" % temperature

    #logger.error("Temperature: %s %s" % ( temperature, id))

    return {
        "temperature" : temperature,
        "id" : id}
