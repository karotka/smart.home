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

import plotly
from plotly.graph_objs import *
pd.options.plotting.backend = 'plotly'

from lib.roomheating import RoomHeating

from datetime import datetime

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


class HeatingChartHandler(ErrorHandler):

    def get(self):
        db = conf.db.conn
        now = datetime.now().strftime("%d.%m.%Y")

        room = self.get_argument('room', "")
        dateFrom = self.get_argument('dateFrom', now)
        dateTo = self.get_argument('dateTo', now)
        col = self.get_argument('col', "temperature")

        
        days = utils.daysBetween(datetime.strptime(dateFrom, "%d.%m.%Y"),
                datetime.strptime(dateTo, "%d.%m.%Y"))

        months = list()
        months.append(datetime.now().strftime("%Y-%m"))
        for day in days:
            months.append("%s-%s" % (day.year, day.month))
        months = set(months)

        filenames = utils.getLogFilenames("sensor_log", days)

        sensorId = conf.HeatingSensors.names.get(room, 0)

        l = list()
        imageUrl = 'static/chart/heating.png'

        for filename in filenames:
            with open('log/%s' % filename, "r", encoding="utf8") as f:
                for line in f.readlines():
                    l.append(json.loads(line))

        df = pd.json_normalize(l)
        df["sensorId"] = df['sensorId'].astype(int)
        dfRoom = pd.DataFrame({"roomId" : conf.HeatingSensors.names.keys(),
                               "sensorId" : conf.HeatingSensors.names.values()})
        dfRoom = dfRoom.set_index(["sensorId"])
        df = df.set_index(["sensorId"]).join(dfRoom).reset_index()
        if sensorId:
            df = df.query("sensorId == %s" % sensorId)

        df = df.rename(columns={"roomId" : "Room"})
        df.date = df.date.str.slice(0, 16)
        pd.to_datetime(df['date'], format="%Y-%m-%d %H:%M")

        ax = df.set_index(
            ["date", "Room"]).unstack()[col].plot.line(
                labels={
                    "value": col.capitalize(),
                    "date": "Date"
                }, height=340, width = 970,
            )
        ax.update_layout(
            title=dict(x=0.5), 
            margin=dict(l=10, r=3, t=20, b=0),
            paper_bgcolor="#2A4B7C",
            plot_bgcolor="#2A4B7C",
            font = dict(color='#fff', size=12),
        )
        ax.update_xaxes(showline=True, linewidth=2,
                linecolor='#757575', gridcolor='#757575')
        ax.update_yaxes(showline=True, linewidth=2,
                linecolor='#757575', gridcolor='#757575')

        colors = (
                "#FFFF7E", #kacka,
                "#89F94F", #koupelna
                "#fd3939",
                "#649CF9" #petr
        )
        for i in range(0, len(ax.data)):
            ax.data[i].line.color = colors[i]

        for month in months:
            res = db.get("heating_time_%s" % month)
            if res:
                items = pickle.loads(res)

                for t1, t2 in zip(*[iter(items)]*2):
                    log.info("%s %s" % (t1, days))
                    if datetime.strptime(t1["date"][:10], "%Y-%m-%d") in days: 
                        ax.add_vrect(x0 = t1["date"], x1 = t2["date"],
                                line_width = 0, opacity = 0.3, fillcolor = "#649CF9")      
        save_html(ax, "static/chart/heating")

        data = dict()
        data["room"] = room
        data["dateFrom"] = dateFrom
        data["dateTo"] = dateTo
        data["imageUrl"] = imageUrl
        data["port"] = conf.Web.Port
        self.render("templ/heating_chart.html", data = data)


class HeatingLogHandler(tornado.web.RequestHandler):

    def get(self):
        db = conf.db.conn
        now = datetime.now()
        month = now.strftime("%Y-%m")
        
        dateTo = self.get_argument('date', now.strftime("%d.%m.%Y"))
        dateFrom = self.get_argument('date', now.strftime("%d.%m.%Y"))

        data = dict()
        data["items"] = list()
        items = pickle.loads(db.get("heating_time_%s" % month))
        for t1, t2 in zip(*[iter(items)]*2):
            if t1["date"][:10] == now.strftime("%Y-%m-%d"): 
                data["items"].append({
                    "len" : (
                        datetime.strptime(t2["date"], "%Y-%m-%d %H:%M:%S") -
                        datetime.strptime(t1["date"], "%Y-%m-%d %H:%M:%S")),
                    "start" : t1["date"],
                    "end" : t2["date"]
                })
        data["items"].reverse()
        data["port"] = conf.Web.Port
        self.render("templ/heating_log.html", data = data)


class Sensor_TempHandler(tornado.web.RequestHandler):

    def get(self):
        log = logging.getLogger('sensor')

        db = conf.db.conn

        sensorId = self.get_argument('id', "")
        data = {
            "sensorId" : int(sensorId),
            "temperature" : float(self.get_argument('t', "")),
            "humidity" : float(self.get_argument('h', "")),
            "pressure" : float(self.get_argument('p', ""))
        }
        db.set("temp_sensor_%s" % sensorId, pickle.dumps(data))

        now = datetime.now()
        data["date"] = now.strftime("%Y-%m-%d %H:%M:%S")
        log.info(data)

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


