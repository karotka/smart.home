import pickle

class RoomHeating:

    def __init__(self, db = None):
        self.db  = db
        self.id = None
        self.dbPrefix = "heating"
        self.name = ""
        self.temperature = .0
        self.humidity = .0

    def load(self):
        try:
            id = self.dbPrefix + "_" + self.id
            o = pickle.loads(self.db.get(id))
            self = o
        except:
            pass
