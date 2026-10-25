#!/usr/bin/python3
"""Where the heat pump's electricity actually goes, room by room.

There is no per-loop flow meter, so this cannot be measured directly. What
we do have, once a minute, is which manifold valves are open
(`control_state.manifold_<room>`) and what the heat pump is drawing
(`hp.power`). Attributing each minute's energy equally across the loops
that were open at that minute gives a defensible estimate of the split.

What it is not:
  * It splits equally per open loop. A long loop through a big room and a
    short one through a hallway get the same share while both are open, so
    a big room is under-counted. Pass --weights to correct that once the
    loop lengths or floor areas are known.
  * It is the heat pump's ELECTRICAL energy, not heat delivered. COP varies
    with flow temperature, so a room heated during a 50 C solar boost looks
    more expensive per delivered kWh than the same room at 32 C.
  * Minutes when the pump ran with every valve shut are reported separately
    rather than spread around: that energy went into the buffer tank, not
    into a room.

Usage:
    python3 room_energy.py [--days 7] [--weights obyvak=2.0,koupelna=0.6]
"""

import argparse
import configparser
import json
import os
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Every room with a loop on the manifold. The garage is on the list because
# it has a valve, not because it is a room anyone heats on purpose.
ROOMS = ["obyvak", "kacka", "kluci", "petr", "loznice", "koupelna",
         "vchod", "garaz"]


def _config():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(BASE_DIR, "conf/config.ini"))
    return cfg["InfluxDb"]


def query(host, port, db, sql):
    url = "http://%s:%s/query?%s" % (host, port, urllib.parse.urlencode(
        {"db": db, "q": sql, "epoch": "s"}))
    with urllib.request.urlopen(url, timeout=120) as r:
        res = json.load(r)["results"][0].get("series")
    return res[0] if res else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--weights", default="",
                    help="room=factor,… — relative loop size; default 1.0 each")
    args = ap.parse_args()

    weights = {r: 1.0 for r in ROOMS}
    for part in filter(None, args.weights.split(",")):
        room, _, val = part.partition("=")
        if room not in weights:
            # Silently dropping an unknown room would answer the question
            # with every weight still at 1.0 and no sign that it had not
            # been asked.
            ap.error("unknown room %r — expected one of: %s"
                     % (room, ", ".join(ROOMS)))
        weights[room] = float(val)

    cfg = _config()
    host, port = cfg["Host"], cfg["Port"]
    window = "now() - %dd" % args.days

    cols = ",".join("last(manifold_%s) as %s" % (r, r) for r in ROOMS)
    state = query(host, port, cfg["Db"],
                  "select %s from control_state where time > %s "
                  "group by time(1m)" % (cols, window))
    power = query(host, port, "hp",
                  "select mean(power) as p from hp where time > %s "
                  "group by time(1m)" % window)
    if not state or not power:
        raise SystemExit("no data for the requested window")

    watts = {t: v for t, v in power["values"] if v}
    idx = {c: i for i, c in enumerate(state["columns"])}

    kwh = {r: 0.0 for r in ROOMS}
    minutes = {r: 0 for r in ROOMS}
    total = buffer_only = 0.0

    for row in state["values"]:
        w = watts.get(row[0])
        if w is None:
            continue
        e = w / 60.0 / 1000.0
        total += e
        # Weighted share: a loop's cut is its weight over the weights of
        # everything open alongside it in the same minute.
        openloops = [r for r in ROOMS if row[idx[r]]]
        if not openloops:
            buffer_only += e
            continue
        wsum = sum(weights[r] for r in openloops)
        for r in openloops:
            kwh[r] += e * weights[r] / wsum
            minutes[r] += 1

    attributed = total - buffer_only
    print("heat pump, last %d days: %.1f kWh total, %.1f kWh of it with every "
          "valve shut (buffer tank)" % (args.days, total, buffer_only))
    print()
    print("%-10s %8s %7s %8s" % ("room", "kWh", "share", "hours"))
    for r in sorted(ROOMS, key=lambda x: -kwh[x]):
        share = 100 * kwh[r] / attributed if attributed else 0
        print("%-10s %8.1f %6.0f%% %8.1f" % (r, kwh[r], share, minutes[r] / 60))


if __name__ == "__main__":
    main()
