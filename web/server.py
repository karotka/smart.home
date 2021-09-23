import argparse
import json
import os
import traceback
import webbrowser

import tornado.web
import tornado.websocket

import methods


class IndexHandler(tornado.web.RequestHandler):

    def get(self):
        self.render("templ/index.html", port = args.port)


class WindowsHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/windows.html", port = args.port)


class HeatingHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/heating.html", port = args.port)

class HeatingSettingHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/heating_setting.html", port = args.port)


class CameraHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/camera.html", port = args.port)


class AlarmHandler(tornado.web.RequestHandler):

    def initialize(self, db = None):
        pass

    def get(self):
        self.render("templ/alarm.html", port = args.port)



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


parser = argparse.ArgumentParser(
    description="Starts a webserver for stuff.")
parser.add_argument("--port", type=int, default=8000,
                    help="The port on which to serve the website.")
args = parser.parse_args()

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
application.listen(args.port)

#webbrowser.open("http://localhost:%d/" % args.port, new = 2)

try:
    tornado.ioloop.IOLoop.instance().start()
except:
    methods.gpio.cleanup()
