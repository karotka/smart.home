"""
"""
import configparser
import redis


class Config():

    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read("/root/project/conf/config.ini")
        self.parse()

        self.db = self.Db(self.config)
        self.heating = self.Heating(self.config)
        #print (self.config.Web.port)

    def parse(self):
        for item in self.config.sections():
            if not hasattr(self, item):
                t = type(item, (object, ), {})()
                for key in self.config[item]:
                    setattr(t, key, self.config[item][key])

                setattr(self, item, t)

    class Db:

        def __init__(self, config):
            self.host = config["Db"]["host"]
            self.port = config["Db"]["port"]
            self.conn = redis.Redis("localhost")

    class Heating:

        def __init__(self, config):
            self.items = dict()
            names = list(map(str.strip, config["Heating"]["roomNames"].split(',')))
            ids = list(map(str.strip, config["Heating"]["roomIds"].split(',')))

            for i in range(0, len(names)):
                self.items[ids[i]] = names[i]



conf = Config()
