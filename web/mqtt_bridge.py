"""MQTT → Redis bridge for the smart.home stack.

Listens on the MQTT broker for topics the publishers (invertor.py on the
Pi3 monitors, the smart-home /sensorTemp endpoint, …) push to, and
writes the same payloads under the legacy Redis keys that the rest of
the codebase (checker.py, web handlers) still reads. That lets us
decouple producers from the Redis encoding without touching the
consumers.

Wire format on MQTT is JSON. The bridge re-encodes as `pickle` for
Redis to stay drop-in compatible with the existing readers
(`pickle.loads(db.get(...))`).
"""

import configparser
import json
import logging
import os
import pickle
from logging.handlers import RotatingFileHandler

import paho.mqtt.client as mqtt
import redis


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(BASE_DIR, "conf/config.ini"))
    return cfg


def _setup_logging():
    log_path = os.path.join(BASE_DIR, "log/mqtt_bridge.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    handler = RotatingFileHandler(log_path, backupCount=5, maxBytes=2_000_000)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s mqtt_bridge [%(process)d] %(levelname)s %(message)s",
        "%b %d %H:%M:%S"))
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# argv position → invertor_N Redis index. Matches invertor.py DEVICE_CONFIG.
POSITION_TO_INDEX = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "proto": 1,
}


class Bridge:
    """One MQTT client → Redis writer.

    `topic` filters are wired in `on_connect`; `dispatch` chooses which
    Redis key to write based on topic prefix. Keep payload decoding
    inside `dispatch` so a bad message on one topic doesn't crash the
    whole loop.
    """

    def __init__(self, cfg):
        self.redis_host = cfg["Db"].get("host")
        self.redis_port = int(cfg["Db"].get("port"))
        self.mqtt_host = cfg["Mqtt"].get("host")
        self.mqtt_port = int(cfg["Mqtt"].get("port"))
        self.db = redis.Redis(self.redis_host, self.redis_port)

    def on_connect(self, client, userdata, flags, rc):
        logging.info("MQTT connected rc=%s", rc)
        client.subscribe([
            ("home/invertor/snapshot/+", 1),
            ("home/temp/sensor/+", 1),
        ])

    def on_disconnect(self, client, userdata, rc):
        logging.warning("MQTT disconnected rc=%s", rc)

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logging.warning("bad json on %s: %s", msg.topic, e)
            return
        try:
            self._dispatch(msg.topic, payload)
        except Exception:
            logging.exception("dispatch failed for %s", msg.topic)

    def _dispatch(self, topic, payload):
        if topic.startswith("home/invertor/snapshot/"):
            position = topic.rsplit("/", 1)[-1]
            idx = POSITION_TO_INDEX.get(position)
            if idx is None:
                logging.warning("unknown invertor position %s", position)
                return
            self.db.set(f"invertor_{idx}", pickle.dumps(payload))
            return
        if topic.startswith("home/temp/sensor/"):
            sensor_id = topic.rsplit("/", 1)[-1]
            self.db.set(f"temp_sensor_{sensor_id}", pickle.dumps(payload))
            return

    def run(self):
        client = mqtt.Client("smart-home-bridge")
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        # block reconnect attempts forever — service restart should be
        # rare; if the broker is down the rest of the stack is broken
        # too.
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        client.loop_forever()


def main():
    _setup_logging()
    cfg = _load_config()
    Bridge(cfg).run()


if __name__ == "__main__":
    main()
