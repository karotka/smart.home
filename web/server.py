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

#import plotly
#from plotly.graph_objs import *
#pd.options.plotting.backend = 'plotly'

from lib.roomheating import RoomHeating

from datetime import datetime, date, timedelta

log = logging.getLogger('web')


class ErrorHandler(tornado.web.RequestHandler):
    """Generates an error response with status_code for all requests."""

    def write_error(self, status_code, **kwargs):
        data = dict()
        self.set_status(status_code)
        if self.settings.get("serve_traceback") and "exc_info" in kwargs:
            # in debug mode, try to send a traceback
            data["status"] = status_code
            data["tb"] = ""
            for line in traceback.format_exception(*kwargs["exc_info"]):
                data["tb"] += line
        
        self.render("templ/error.html", data = data)


def save_html(graph, name):
    graph.show()
    graph.write_html(name + ".html")


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
        log.info("Ping from IP:<%s> time:%s" % (remoteIp, t))
        self.write("")


class WindowsHandler(tornado.web.RequestHandler):
    
    def get(self):
        db = conf.db.conn

        data = dict()
        data["rooms"] = list()
        data["port"] = conf.Web.Port
        for id, name in conf.Blinds.items.items():
            data["rooms"].append({
                "id" : id,
                "name" : name
            })

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
        sensorId = conf.HeatingSensors.names.get(id)

        data = db.get("temp_sensor_%s" % sensorId)
        if data:
            data = pickle.loads(data)
            actualHumidity = data.get("humidity")
            actualTemperature = data.get("temperature")

        if room is None:
            temperature = conf.Heating.minimalTemperature
            humidity = "-"
        else:
            room = pickle.loads(room)
            reqTemperature = room.get("temperature")

        data = dict()
        data["port"] = conf.Web.Port
        data["id"] = id

        data["roomName"] = conf.Heating.items.get(id, "unknown")
        data["reqTemperature"] = "%.1f" % reqTemperature
        data["actualTemperature"] = "%.1f" % actualTemperature
        data["actualHumidity"] = actualHumidity

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


class SolarChartHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/solar_chart.html", data = data)


class HeatingChartHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/heating_chart.html", data = data)


class HumidityChartHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/humidity_chart.html", data = data)


class PressureChartHandler(tornado.web.RequestHandler):

    def get(self):
        data = dict()
        data["port"] = conf.Web.Port
        self.render("templ/pressure_chart.html", data = data)


class HeatingLogHandler(ErrorHandler):

    def get(self):
        db = conf.db.conn
        now = datetime.now()
        month = now.strftime("%Y-%m")
        
        dateTo = self.get_argument('date', now.strftime("%d.%m.%Y"))
        dateFrom = self.get_argument('date', now.strftime("%d.%m.%Y"))

        data = dict()
        data["items"] = list()
        items = pickle.loads(db.get("heating_time_%s" % month))
       
        suma = timedelta(0)
        for t1, t2 in zip(*[iter(items)]*2):
            if t1["date"][:10] == now.strftime("%Y-%m-%d"): 
                div = datetime.strptime(t2["date"], "%Y-%m-%d %H:%M:%S") - datetime.strptime(t1["date"], "%Y-%m-%d %H:%M:%S")
                data["items"].append({
                    "len" : div,
                    "start" : t1["date"],
                    "end" : t2["date"]
                })
                suma += div
        
        data["suma"] = utils.strfdelta(suma, "{hours}h {minutes}m {seconds}s")
        data["items"].reverse()
        data["port"] = conf.Web.Port
        self.render("templ/heating_log.html", data = data)


class Sensor_TempHandler(tornado.web.RequestHandler):

    def get(self):
        log = logging.getLogger('web')

        db = conf.db.conn
        infx = conf.Influx.getDfClient()

        sensorId = self.get_argument('id', "")
        data = {
            "sensorId" : int(sensorId),
            "temperature" : float(self.get_argument('t', "")),
            "humidity" : float(self.get_argument('h', "")),
            "pressure" : float(self.get_argument('p', ""))
        }
        db.set("temp_sensor_%s" % sensorId, pickle.dumps(data))
        df = pd.DataFrame(data, index=[0])
        df["time"] = pd.to_datetime('today').now()
        df.set_index(['time'], inplace = True)
        infx.write_points(df, 'sensor',  time_precision=None)
        log.info("Sensor: %s" % data)

        self.write(data)


class Sensor_TempListHandler(tornado.web.RequestHandler):

    def get(self):
        db = conf.db.conn

        data = dict()
        for item in db.keys("temp_sensor_*"):
            data[utils.toStr(item)] = pickle.loads(db.get(item))
        self.write(data)


class Room_List(tornado.web.RequestHandler):

    def get(self):
        self.write(conf.Heating.items)

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

        log.debug("Message: %s" % message)
        try:
            result = getattr(
                methods,
                json_rpc["method"])(**json_rpc["params"])
            error = None
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
    (r"/solar_chart.html", SolarChartHandler),
    (r"/heating_chart.html", HeatingChartHandler),
    (r"/humidity_chart.html", HumidityChartHandler),
    (r"/pressure_chart.html", PressureChartHandler),
    (r"/heating_log.html", HeatingLogHandler),
    (r"/camera.html", CameraHandler),
    (r"/alarm.html", AlarmHandler),
    (r"/websocket", WebSocket),
    (r'/static/(.*)', tornado.web.StaticFileHandler, {
        "path": os.getcwd() + "/static/"}),
    (r"/sensorTemp", Sensor_TempHandler),
    (r"/roomsList", Room_List),
    (r"/sensorTempList", Sensor_TempListHandler),
]

application = tornado.web.Application(handlers, debug = True)
application.listen(conf.Web.Port)

try:
    tornado.ioloop.IOLoop.instance().start()
except Exception as e:
    pass


