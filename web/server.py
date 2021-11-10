import json
import os
import traceback
import webbrowser

import tornado.web
import tornado.websocket

from config import conf

import methods
import utils
import pickle
import logging
import pandas as pd
import matplotlib.pyplot as plt

from lib.roomheating import RoomHeating

from datetime import datetime

log = logging.getLogger('web')

class IndexHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/index.html", data = data)


class PingHandler(tornado.web.RequestHandler):

    def get(self):
        t = self.get_argument("t", "")
        remoteIp = self.request.headers.get("X-Real-IP") or \
                self.request.headers.get("X-Forwarded-For") or \
                self.request.remote_ip
        log.info("IP:%s Time:%s" % (remoteIp, t))
        self.write("")



class WindowsHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/windows.html", data = data)


class LightHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        data["lights1"] = list()
        data["lights2"] = list()

        names1 = conf.Lights.names[:len(conf.Lights.names)//2]
        ids1   = conf.Lights.ids[:len(conf.Lights.ids)//2]
        items1 = dict(zip(ids1, names1))

        i = 0
        for id, name in items1.items():
            data["lights1"].append({
                "id" : id,
                "name" : name,
                "style" : "w l1" if i < 2 else "w r1"
            })
            i = i + 1

        names2 = conf.Lights.names[len(conf.Lights.names)//2:]
        ids2   = conf.Lights.ids[len(conf.Lights.ids)//2:]
        items2 = dict(zip(ids2, names2))

        i = 0
        for id, name in items2.items():
            data["lights2"].append({
                "id" : id,
                "name" : name,
                "style" : "w l2" if i < 2 else "w r2"
            })
            i = i + 1

        self.render("templ/light.html", data = data)


class HeatingHandler(tornado.web.RequestHandler):

    def get(self):
        db = conf.db.conn

        data = dict()
        data["port"] = conf.Web.Port
        data["ids"] = list(conf.Heating.items.keys())
        data["rooms"] = list()
        for id, name in conf.Heating.items.items():
            try:
                room = pickle.loads(db.get("heating_" + id))
            except:
                room = dict()
            data["rooms"].append({
                "id" : id,
                "name" : name,
                "temperature" : "%.1f" % room.get("temperature", .0),
                "actualTemperature" : .0,
                "humidity" : .0
            })

        self.render("templ/heating.html", data = data)


class HeatingSettingHandler(tornado.web.RequestHandler):

    def get(self):
        db = conf.db.conn
        id = self.get_argument('id', "")
        dbId = "heating_" + self.get_argument('id', "")

        room = db.get(dbId)
        if room is None:
            temperature = conf.Heating.minimalTemperature
        else:
            room = pickle.loads(room)
            temperature = room.get("temperature")

        data = dict()
        data["port"] = conf.Web.Port
        data["id"] = id

        data["roomName"] = conf.Heating.items.get(id, "unknown")
        data["temperature"] = "%.1f" % temperature
        data["humidity"] = 0

        self.render("templ/heating_setting.html", data = data)


class CameraHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/camera.html", data = data)


class AlarmHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/alarm.html", data = data)


class HeatingChartHandler(tornado.web.RequestHandler):

    def get(self):
        l = list()
        imageUrl = 'static/chart/heating.png'

        with open('log/sensor_log', "r", encoding="utf8") as f:
            for line in f.readlines():
                l.append(json.loads(line))

        df = pd.json_normalize(l)
        df.date = df.date.str.slice(0, 16)
        pd.to_datetime(df['date'], format="%Y-%m-%d %H:%M")

        fig, ax = plt.subplots()
        fig.patch.set_facecolor('#2A4B7C')
        ax = df.set_index(
            ["date", "sensorId"]).unstack().temperature.plot(
                ax = ax, figsize = (14,5), rot=90,
                color = ("#ffffff", "#00FFFF", "#DC143C", "#00FA9A", "#F0E68C", "#FF00FF" ))
        ax.set_facecolor("#4dabf7")
        ax.tick_params(colors='#fff')
        ax.figure.savefig(imageUrl)

        data = dict()
        data["imageUrl"] = imageUrl
        data["port"] = conf.Web.Port
        self.render("templ/heating_chart.html", data = data)


class Sensor_TempHandler(tornado.web.RequestHandler):

    def get(self):
        log = logging.getLogger('sensor')

        db = conf.db.conn

        sensorId = self.get_argument('id', "")
        data = {
            "sensorId" : sensorId,
            "temperature" : float(self.get_argument('t', "")),
            "humidity" : float(self.get_argument('h', "")),
            "pressure" : float(self.get_argument('p', ""))
        }
        db.set("temp_sensor_%s" % sensorId, pickle.dumps(data))

        now = datetime.now()
        data["date"] = now.strftime("%Y-%m-%d %H:%M:%S:%f")
        log.info(data)

        self.write(data)


class Sensor_TempListHandler(tornado.web.RequestHandler):

    def get(self):
        db = conf.db.conn

        data = dict()
        for item in db.keys("temp_sensor_*"):
            data[utils.toStr(item)] = pickle.loads(db.get(item))
        self.write(data)


"""
Method router for WebSocket requests
This class call method by method name from javascript in the
methods.py module
"""

class WebSocket(tornado.websocket.WebSocketHandler):

    def on_message(self, message):
        """
        """

        json_rpc = json.loads(message)

        try:
            result = getattr(
                methods,
                json_rpc["method"])(**json_rpc["params"])
            error = None
            #logger.error("Result: %s" % result)
        except:
            result = traceback.format_exc()
            error = 1
            log.error("Error: %s" % result)

        self.write_message(
            json.dumps({
                "result": result,
                "error": error,
                "router": json_rpc["router"],
                "id": json_rpc["id"]},
                separators=(",", ":")))


handlers = [
    (r"/", IndexHandler),
    (r"/ping", PingHandler),
    (r"/windows.html", WindowsHandler),
    (r"/light.html", LightHandler),
    (r"/heating.html", HeatingHandler),
    (r"/heating_setting.html", HeatingSettingHandler),
    (r"/heating_chart.html", HeatingChartHandler),
    (r"/camera.html", CameraHandler),
    (r"/alarm.html", AlarmHandler),
    (r"/websocket", WebSocket),
    (r'/static/(.*)', tornado.web.StaticFileHandler, {
        "path": os.getcwd() + "/static/"}),
    (r"/sensorTemp", Sensor_TempHandler),
    (r"/sensorTempList", Sensor_TempListHandler),
]

application = tornado.web.Application(handlers, debug = True)
application.listen(conf.Web.Port)

try:
    tornado.ioloop.IOLoop.instance().start()
except:
    pass
    #log.error("ERROR")
