"""
An entire file for you to expand. Add methods here, and the client should be
able to call them with json-rpc without any editing to the pipeline.
"""
#import RPi.GPIO as gpio

import config


def heating(**kwargs):

    db = config.conf.db.conn

    direction = kwargs.get("direction", None)
    id = "heating_" + kwargs.get("id", "")

    temperature = int(db.get(id))

    #print (conf.port)
    if direction == "up":
        temperature += 1
    elif direction == "down":
        temperature -= 1
    db.set(id, temperature)

    return temperature
