import json
import os
import traceback
import webbrowser

import tornado.web
import tornado.websocket

import config
import methods




class IndexHandler(tornado.web.RequestHandler):

    def get(self):
        self.render("templ/index.html")


class WindowsHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/windows.html")


class HeatingHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        data = dict()
        data["port"] = config.conf.Web.port
        data["rooms"] = config.conf.heating.items
        data["temperature"] = 23.5

        self.render("templ/heating.html", data = data)

class HeatingSettingHandler(tornado.web.RequestHandler):

    def initialize(self):
        pass

    def get(self):
        db = config.conf.db.conn
        id = self.get_argument('id', "")
        dbId = "heating_" + self.get_argument('id', "")

        temperature = db.get(dbId)
        if not temperature:
            temperature = 0
            db.set(dbId, 0)
        else:
            temperature = int(temperature)

        data = dict()
        data["port"] = config.conf.Web.port
        data["id"] = id

        data["roomName"] = config.conf.heating.items.get(id, "unknown")
        data["temperature"] = temperature

        self.render("templ/heating_setting.html", data = data)


class CameraHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/camera.html")


class AlarmHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/alarm.html")


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
        except:
            result = traceback.format_exc()
            error = 1

        self.write_message(
            json.dumps({
                "result": result, "error": error,
                "id": json_rpc["id"]},
                separators=(",", ":")))


handlers = [
    (r"/", IndexHandler),
    (r"/windows.html", WindowsHandler),
    (r"/heating.html", HeatingHandler),
    (r"/heating_setting.html", HeatingSettingHandler),
    (r"/camera.html", CameraHandler),
    (r"/alarm.html", AlarmHandler),
    (r"/websocket", WebSocket),
    (r'/static/(.*)', tornado.web.StaticFileHandler, {
        "path": os.getcwd() + "/static/"})
]

application = tornado.web.Application(handlers, debug = True)
application.listen(config.conf.Web.port)

try:
    tornado.ioloop.IOLoop.instance().start()
except:
    methods.gpio.cleanup()
