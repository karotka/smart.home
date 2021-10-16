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
    else:
        conf.Log.log.info("GET http://%s/?p=%s&v=%s" % (conf.Lights.hwIp,
                getPort(id), 1 if direction == "on" else 0))

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

    direction = kwargs.get("direction", None)
    id = "heating_" + kwargs.get("id", "")

    temperature = utils.toFloat(db.get(id))

    #print (conf.port)
    if direction == "up":
        temperature = "%.1f" % (temperature + .2)

    elif direction == "down":
        if temperature > conf.Heating.minimalTemperature:
            temperature = "%.1f" % (temperature - .2)

    db.set(id, temperature)

    return {
        "temperature" : temperature,
        "id" : id}
