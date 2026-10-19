"""Historise the control plane: Redis live state -> InfluxDB.

`checker.py` makes every heating decision there is and writes nothing to
InfluxDB. All of it — which rooms were calling for heat, what mode the
scheduler was in, whether the solar boost was engaged, what each room was
asked to reach — exists only as "now" in Redis. The sole record was the
daemon log, which rotates after five days.

That gap has a cost. Reconstructing how much energy went into heating the
garage on 2026-10-12/13 (8-10 kWh/day, 40-45 % of the heat pump's draw that
day) was only possible because the log happened to still hold the manifold
transitions, and in five days it would not have. Any question of the form
"what was the house actually doing when it used that energy" is unanswerable
beyond that window.

So this records the control plane rather than one value: a declarative list of
Redis keys, what they mean and where they land. Adding a signal is a line in
SPEC, not another script.

Deliberately reads **Redis, not the heating path** — it cannot slow down or
break `checker.py`, which is the one daemon in the house that must not stall.

Run as a service (see service/state_recorder.service); samples every
INTERVAL seconds into measurement `control_state`, one point, many fields.

## Why the manifold is expanded per room

The raw value is a 9-character bit string, one character per manifold port.
Stored as-is it would be an opaque string nobody can query. `config.ini`
already maps sensor -> room -> port, so the recorder expands it into
`manifold_<room>` fields. Hours of heating per room then fall straight out of
an InfluxDB query, which is the form every question about heat actually takes
— and it is what makes a per-room energy signature possible instead of one
lumped figure for the whole house.
"""

import ast
import configparser
import json
import logging
import os
import pickle
import time
import urllib.parse
import urllib.request
from logging.handlers import RotatingFileHandler

import redis


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTERVAL = 60
MEASUREMENT = "control_state"


# ---------------------------------------------------------------- decoders

def as_int(raw):
    return int(raw)


def as_float(raw):
    return float(raw)


def as_text(raw):
    """A string field. Keep the readable value and let callers match on it."""
    return raw.decode("utf-8", errors="replace")


# Which Redis keys to record and how to read them. To add a signal, add a row.
#   (redis key, field name, decoder)
SPEC = [
    ("heating_state",           "heating_state",      as_int),
    ("heating_time",            "heating_time",       as_int),
    ("__heatingCounter",        "heating_counter",    as_int),
    ("heating_sched_mode",      "sched_mode",         as_text),
    ("solar_boost_active",      "boost_active",       as_int),
    ("solar_boost_prev_target", "boost_prev_target",  as_int),
    # Flow temperature at the manifold, from the 100k NTC on the manifold
    # board: it pings /ping?t=&te= every 20 s and the handler parks `te`
    # in Redis under `heating_watter` (two t's — the key is spelled that
    # way in server_fastapi.py, don't "fix" it without changing both).
    # This used to land in its own measurement `heating_water`, written by
    # something that is not in this repo and died 2026-06-13; recording it
    # here as a field of control_state revives the signal in the place
    # every other control value already lives.
    ("heating_watter",          "water_manifold_c",   as_float),
]


def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(BASE_DIR, "conf/config.ini"))
    return cfg


def _setup_logging():
    path = os.path.join(BASE_DIR, "log/state_recorder.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h = RotatingFileHandler(path, backupCount=3, maxBytes=1_000_000)
    h.setFormatter(logging.Formatter(
        "%(asctime)s state_recorder [%(process)d] %(levelname)s %(message)s",
        "%b %d %H:%M:%S"))
    log = logging.getLogger()
    log.addHandler(h)
    log.setLevel(logging.INFO)


def manifold_port_to_room(cfg):
    """{port index -> room id} from the sensor/room/port tables in config.ini.

    A room can own several ports (the living room spans two loops); a port
    belongs to one room, so inverting the mapping is safe.
    """
    sensor_ids = [s.strip() for s in cfg["HeatingSensors"]["sensorIds"].split(",")]
    room_ids = [r.strip() for r in cfg["HeatingSensors"]["roomIds"].split(",")]
    by_sensor = dict(zip(sensor_ids, room_ids))
    mapping = ast.literal_eval(cfg["HeatingSensors"]["mapSensorsToManifold"])
    out = {}
    for sensor, ports in mapping.items():
        room = by_sensor.get(str(sensor))
        if not room:
            continue
        for p in ports:
            out[int(p)] = room
    return out


def collect(db, cfg, port_room, rooms):
    """One snapshot of the control plane as {field: value}."""
    fields = {}

    for key, field, decode in SPEC:
        raw = db.get(key)
        if raw is None:
            continue
        try:
            fields[field] = decode(raw)
        except (ValueError, TypeError) as e:
            logging.warning("key %s: cannot decode %r (%s)", key, raw[:40], e)

    # Manifold bit string -> one field per room, so "hours heated" is a query.
    raw = db.get("heating_manifold_state")
    if raw:
        state = raw.decode("ascii", errors="replace")
        for port, room in port_room.items():
            if port < len(state):
                fields["manifold_" + room] = 1 if state[port] == "1" else 0

    # Per-room setpoints, pickled dicts written by checker.py.
    for room in rooms:
        raw = db.get("heating_" + room)
        if not raw:
            continue
        try:
            val = pickle.loads(raw)
        except Exception:
            continue
        t = val.get("temperature") if isinstance(val, dict) else None
        if t is not None:
            fields["target_" + room] = float(t)

    return fields


def line_protocol(fields):
    """InfluxDB line protocol. Strings quoted, ints suffixed i, floats bare."""
    parts = []
    for k, v in sorted(fields.items()):
        if isinstance(v, str):
            parts.append('%s="%s"' % (k, v.replace('"', '\\"')))
        elif isinstance(v, bool):
            parts.append("%s=%di" % (k, int(v)))
        elif isinstance(v, int):
            parts.append("%s=%di" % (k, v))
        else:
            parts.append("%s=%s" % (k, v))
    return MEASUREMENT + " " + ",".join(parts)


def write(host, port, db_name, line):
    url = "http://%s:%s/write?%s" % (host, port, urllib.parse.urlencode({"db": db_name}))
    req = urllib.request.Request(url, data=line.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        if r.status not in (200, 204):
            raise RuntimeError("influx returned %s" % r.status)


def main():
    _setup_logging()
    cfg = _load_config()
    db = redis.Redis(cfg["Db"].get("host"), int(cfg["Db"].get("port")))
    influx = (cfg["Influx"].get("host"), cfg["Influx"].get("port"),
              cfg["Influx"].get("db"))
    port_room = manifold_port_to_room(cfg)
    rooms = [r.strip() for r in cfg["HeatingSensors"]["roomIds"].split(",")]
    logging.info("recording %d keys + %d manifold ports + %d room targets every %ds",
                 len(SPEC), len(port_room), len(rooms), INTERVAL)

    while True:
        try:
            fields = collect(db, cfg, port_room, rooms)
            if fields:
                write(*influx, line_protocol(fields))
        except Exception:
            # Never die on a transient Redis/Influx hiccup — this is a
            # recorder, a gap in it is far less bad than it needing a restart.
            logging.exception("sample failed")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
