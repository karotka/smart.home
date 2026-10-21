#!/usr/bin/python

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import datetime
from influxdb import DataFrameClient
import paho.mqtt.client as mqtt 
import json
import numpy as np
import traceback
import tinytuya

broker_address="192.168.0.224"
pidfile = "/tmp/tuya.pid"

mqttClient = mqtt.Client("Tuya") #create new instance


class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(Encoder, self).default(obj)

def getMqttClient():
    if not mqttClient.is_connected():
        mqttClient.connect(broker_address) #connect to broker
    return mqttClient

def getClient():
    while True:
        try:
            return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')
        except:
            logging.error(e, exc_info = True)
            time.sleep(3)


def createPid():

    pid = str(os.getpid())

    if os.path.isfile(pidfile):
        print ("%s already exists, exiting" % pidfile)
        sys.exit()

    f = open(pidfile, 'w')
    f.write(pid)

createPid()


def createLog():
    """
    Creates a rotating log
    """
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log/tuya_log")
    # maxBytes matters: without it the handler never rotates (the default is 0
    # = unlimited) and backupCount is dead code. This log had grown to 82 MB,
    # almost all of it the same AttributeError traceback once a minute.
    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024,
                                  backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


GRID_DEVICE_ID = "bf804257239825cfb7xyjf"      # "Solar in" — the breaker before the grid
SNAPSHOT = "/home/karotka/git/smart.home/web/conf/snapshot.json"

# Address that last answered, so the switch goes to the same place the state
# was just read from. None means "use whatever snapshot.json says".
_lastIp = [None]


def gridDevice(ip=None):
    """Resolve the breaker from snapshot.json instead of a hardcoded address.

    The address used to be baked in as 192.168.0.166. DHCP moved the device to
    .172 and from 2026-10-11 every call failed: `status()` returned an error
    dict with no "dps", `data.get("dps").get("1")` raised AttributeError, and
    on_message swallowed it into the log. The breaker sat closed for ten days
    while the code "decided" to open it once a minute.

    snapshot.json is the right source because `tuya_rediscover.timer` already
    refreshes it hourly for exactly this reason — it just was never wired up
    here. Resolving per call also means a DHCP move self-heals within a minute
    rather than needing an edit.
    """
    with open(SNAPSHOT) as f:
        snap = json.load(f)
    devs = snap.get("devices", snap)
    devs = devs if isinstance(devs, list) else list(devs.values())
    for d in devs:
        if d.get("id") == GRID_DEVICE_ID:
            dev = tinytuya.OutletDevice(dev_id=d["id"], address=ip or d["ip"],
                                        local_key=d.get("key"),
                                        version=float(d.get("ver", 3.3)))
            dev.set_socketTimeout(5)
            return dev
    raise RuntimeError("grid breaker %s not in %s" % (GRID_DEVICE_ID, SNAPSHOT))


def findGridIp():
    """Ask the device where it is, by broadcast.

    These devices will not take a static address and DHCP moves them around,
    which is what broke this script for ten days. snapshot.json is refreshed
    hourly by tuya_rediscover.timer, so on its own it leaves up to an hour of
    failure after a move; a broadcast closes that to one cycle. Used only as
    a fallback, because it is slower and noisier than reading the file.
    """
    try:
        found = tinytuya.find_device(dev_id=GRID_DEVICE_ID) or {}
    except Exception as e:
        logging.warning("grid breaker discovery failed: %s" % e)
        return None
    return found.get("ip")


def gridState():
    """Current breaker state as True/False, or None if it cannot be read.

    Returning None rather than raising keeps a momentary network blip from
    tearing through on_message, but the caller must treat None as "unknown"
    and do nothing — never as "off".
    """
    for ip in (None, "rediscover"):
        if ip == "rediscover":
            ip = findGridIp()
            if not ip:
                break
            logging.info("grid breaker rediscovered at %s" % ip)
        try:
            data = gridDevice(ip).status()
        except Exception as e:
            logging.warning("grid breaker unreachable: %s" % e)
            continue
        dps = (data or {}).get("dps")
        if dps and "1" in dps:
            _lastIp[0] = ip
            return bool(dps["1"])
        logging.warning("grid breaker gave no state: %s" % (data,))
    return None


def gridOff(bv):
    state = gridState()
    if state is None:
        return                       # unknown — leave the breaker alone
    if state:
        gridDevice(_lastIp[0]).turn_off()
        logging.info("Battery voltage is <%sV>, turn it off" % bv)
    else:
        logging.info("Battery voltage is <%sV> leave the switch off" % (bv,))


def gridOn(bv):
    state = gridState()
    if state is None:
        return
    if not state:
        gridDevice(_lastIp[0]).turn_on()
        logging.info("Battery voltage is <%sV>, turn it on" % bv)
    else:
        logging.info("Battery voltage is <%sV> leave the switch on" % (bv,))


def doIt(dt, period, data):

    # pouze, pokud se nabiji baterie
    #if batteryCurrent, batteryDischargeCurrent > 0 \
    #    # a napeti baterie je vetsi nez 50V
    #    and batteryVoltage > 50:
    #    pass

    d = data["invertor1"]
    batteryVoltage = float(d["batteryVoltage"])
    #logging.info("Battery volatge is <%sV>" % batteryVoltage)
  
    # case odpojit CEZ
    if batteryVoltage > 53.5:
        gridOff(batteryVoltage)

    # case pripojit CEZ
    elif batteryVoltage < 52:
        gridOn(batteryVoltage)

    else:
        pass
        #gridOff(batteryVoltage)

def on_connect(client, userdata, flags, rc):
    #print(f"Connected with result code {rc}")
    client.subscribe("home/invertor/actual/")


oldMinute = 0
oldHour   = 0
def on_message(client, userdata, msg):
    global oldMinute
    global oldHour

    dt = pd.to_datetime('today').now()
    minute = dt.minute
    hour = dt.hour

    # one time per hour
    #if oldHour != hour:
    #    doIt(dt, "hour", msg.payload)

    # one time per minute
    try:
        if oldMinute != minute:
            logging.info("Recv. minute message: %s" % (dt,))
            doIt(dt, "minute", json.loads(msg.payload))

        #doIt(dt, "actual", json.loads(msg.payload))

    except Exception as e:
        #print ("aaaa")
        logging.error("Exception occurred", exc_info = True)

    oldMinute = minute
    oldHour = hour

try:
    client = mqtt.Client("tuya-client") # client ID "mqtt-test"
    client.on_connect = on_connect
    client.on_message = on_message
    #client.username_pw_set("myusername", "aeNg8aibai0oiloo7xiad1iaju1uch")
    client.connect(broker_address, 1883)
    client.loop_forever()  # Start networking daemon

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    os.unlink(pidfile)
