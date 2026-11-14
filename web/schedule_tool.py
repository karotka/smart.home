#!/usr/bin/env python3
"""Inspect conf/schedule.json and run one of its rules on demand.

There is no web UI for the schedule yet, so this is how a rule gets
tested without waiting for its hour -- and how a hand edit gets checked
before the daemon finds the typo at seven in the morning.

    docker exec smart-home python3 schedule_tool.py list
    docker exec smart-home python3 schedule_tool.py run rolety_vecer

`run` sends the action straight away and does NOT touch the "ran this
slot" flag in redis, so a test does not cancel tonight's real run (and
does not substitute for it either).
"""
import argparse
import logging
import sys
import time

import checker
from config import conf
import utils

DAYS_CS = ("po", "út", "st", "čt", "pá", "so", "ne")


def fmtDays(days):
    if days == "*":
        return "každý den"
    return " ".join(DAYS_CS[d] for d in sorted(days))


def fmtWhen(t):
    """Czech weekday, because strftime %a here is whatever the C locale says."""
    if t is None:
        return "-"
    return "%s %s" % (DAYS_CS[t.tm_wday], time.strftime("%d.%m. %H:%M", t))


def nextFire(rule, now=None):
    """When this rule is next due. Not the catch-up window, the stroke."""
    now = now or time.localtime()
    base = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0,
                        0, 0, -1))
    for day in range(0, 9):
        t = time.localtime(base + day * 86400 + rule["at"] * 60)
        if rule["days"] != "*" and t.tm_wday not in rule["days"]:
            continue
        if time.mktime(t) > time.mktime(now):
            return t
    return None


def cmdList():
    rules, errors = checker.loadSchedule()
    for e in errors:
        print("CHYBA: %s" % e, file=sys.stderr)

    db = conf.db.conn
    for r in rules:
        last = utils.toStr(db.get("sched_%s_date" % r["id"])) or "-"
        nxt = nextFire(r)
        what = r["action"]
        if r["position"] is not None:
            what = "position %d%%" % r["position"]
        print("%-20s %-5s %-12s %-8s %s"
              % (r["id"],
                 "%02d:%02d" % (r["at"] // 60, r["at"] % 60),
                 fmtDays(r["days"]),
                 what,
                 ", ".join("%s:%s" % t for t in r["targets"])))
        print("%-20s %s | dohnat do %d min | naposled %s | dalsi %s"
              % ("", "zapnuto" if r["enabled"] else "VYPNUTO",
                 r["catchup_min"], last,
                 fmtWhen(nxt)))
    if not rules:
        print("zadna pravidla")
    return 1 if errors else 0


def cmdRun(ruleId):
    rules, errors = checker.loadSchedule()
    for e in errors:
        print("CHYBA: %s" % e, file=sys.stderr)
    byId = {r["id"]: r for r in rules}
    if ruleId not in byId:
        print("pravidlo %r neexistuje (mam: %s)"
              % (ruleId, ", ".join(sorted(byId)) or "nic"), file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    c = checker.Checker(logging.getLogger("schedule_tool"))
    t0 = time.time()
    ok, msg = c.schedRun(byId[ruleId])
    print("%s: %s (%.2f s)" % ("OK" if ok else "SELHALO", msg,
                               time.time() - t0))
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="vypsat pravidla a kdy pobezi")
    runP = sub.add_parser("run", help="spustit pravidlo hned")
    runP.add_argument("id")
    a = p.parse_args()
    return cmdList() if a.cmd == "list" else cmdRun(a.id)


if __name__ == "__main__":
    sys.exit(main())
