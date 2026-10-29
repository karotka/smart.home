#!/usr/bin/python3

import os
import time
import configparser
import logging
from influxdb import DataFrameClient, InfluxDBClient
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from dateutil import tz
from logging.handlers import RotatingFileHandler
import pandas as pd
import getopt
import sys

modes = ("hourly", "daily", "monthly")

try:
    args = sys.argv[1:]
    opts, args = getopt.getopt(args, "m:d", ["mode=", "date="])
except IndexError as e:
    sys.exit(1)


for opt, arg in opts:
    if opt in ['-m', '--mode']:
        mode = arg
        if mode not in modes:
            print ("Mode has to be in: %s", modes)
            sys.exit(0)

    elif opt in ('-d', '--date'):
        date = arg

if mode == "hourly":
    try:
        dt = datetime.strptime(date, "%Y-%m-%d %H")
    except ValueError as e:
        print (e)
        sys.exit(0)
    hour = (dt + relativedelta(hours=1)).strftime("%Y-%m-%d %H")
    hourPast = dt.strftime("%Y-%m-%d %H")

elif mode == "daily":
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        print (e)
        sys.exit(0)
    day = (dt + relativedelta(days=1)).strftime("%Y-%m-%d")
    dayPast = dt.strftime("%Y-%m-%d")

elif mode == "monthly":
    dt = datetime.strptime("%s-01" % date, "%Y-%m-%d")
    month = date
    nextMonth = (dt + relativedelta(months=1)).strftime("%Y-%m-%d")

#print ("day: %s pass: %s" % (day, dayPast))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, 'conf/config.ini'))


def createLog():
    """
    Creates a rotating log
    """
    handler = RotatingFileHandler(os.path.join(BASE_DIR, 'log/aggregate_log'), backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s aggregate [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


def getClient():
    return DataFrameClient(
            config['InfluxDb']['Host'],
            int(config['InfluxDb']['Port']),
            config['InfluxDb']['User'],
            config['InfluxDb']['Password'],
            config['InfluxDb']['Db'])


client = getClient()


# --- timestamps -------------------------------------------------------------
# There are two different things called "a time" here and the old code used one
# formula for both, with a `tzshift` bolted on that made each of them wrong in a
# different way.
#
#   * A measurement row is an INSTANT. `invertor` and the `bms_*` series are
#     stamped when the sample was taken, so "the 24th" means the window between
#     two local midnights — localNs().
#   * A rolled-up row is a LABEL. invertor_daily and invertor_monthly hold one
#     row per calendar day/month, stamped at that date's midnight UTC. It is a
#     name for the day, not a moment in it — stampNs().
#
# Adding the UTC offset to a .timestamp() that had already applied it pushed
# every daily window to 02:00 -> 02:00 local. The damage showed on 2026-10-25,
# the day the clocks went back: the offset the shift used (now +1) no longer
# matched the offset inside the window (+2), the window opened at 23:00Z on the
# 24th, and that one stray hour was written out as the whole of the 24th —
# 783 Wh in place of 29 kWh. The same hour-wide slip put a duplicate October
# into invertor_monthly, stamped 2026-09-30T23:00Z.
LOCAL = tz.tzlocal()

# The bank: 5 NMC packs + the LFP. Battery energy is taken from their shunts
# rather than from the inverter, whose current register is an integer that
# reads 0 below about 5 A — every slow discharge was being rounded away.
BMS_MIN_PACKS = 6


def localNs(dateStr, pattern="%Y-%m-%d"):
    """Epoch ns of local midnight on `dateStr`. DST-correct: .timestamp() on a
    naive datetime applies the offset in force on that date, not today's."""
    return int(datetime.strptime(dateStr, pattern).timestamp() * 1e9)


def stampNs(dateStr, pattern="%Y-%m-%d"):
    """Epoch ns of the label a rolled-up row carries: that date at midnight UTC."""
    dt = datetime.strptime(dateStr, pattern).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1e9)


# AC volts above which the mains is actually present. The inverter reports a
# clean 0 when its input is dead, so there is no middle ground to worry about.
GRID_LIVE_V = 50

# How close output and input volts have to be before the unit counts as
# bypassing rather than inverting. In bypass they are the same measurement and
# agree to 0.01 V; inverting, the gap is 10 V and more. 1 V is slack enough for
# a minute that straddles a transition and tight enough never to fire on one.
BYPASS_V = 1.0

columns = [
    "deviceNumber", "batteryCurrent", "batteryDischargeCurrent",
    "batteryVoltage", "gridVoltage", "outputPowerActive",
    "outputPowerApparent", "outputVoltage", "solarCurrent", "solarVoltage",
    "solarPowerTotal", "solarPowerCurtailed"]


def getMonthlyRows(fromStr, toStr, columns = "*"):
    # Reads invertor_daily, whose rows are labels -> stampNs.
    fr = stampNs(fromStr)
    to = stampNs(toStr)
    query = "select %s from invertor_daily where time >= %d and time < %d" % (
            ",".join(columns), fr, to)
    logging.debug(query)
    return client.query(query)


def dropMonthlyRows(fromStr):
    fr = stampNs("%s-01" % fromStr)
    to = fr + 86400*1e9      # the whole label day. Was 1440e9 — 24 minutes,
                             # which never reached the row it meant to delete.
    query = "delete from invertor_monthly where time >= %d and time < %d" % (fr, to)
    logging.debug(query)
    client.query(query)


def dropDailyRows(fromStr, toStr, invertor=None):
    fr = stampNs(fromStr)
    to = stampNs(toStr)
    query = "delete from invertor_daily where time >= %d and time < %d" % (fr, to)
    if invertor:
        query += " and devNumber = '%s'" % invertor
    logging.debug(query)
    client.query(query)


def getDailyRows(fromStr, toStr, invertor, columns = "*"):
    # Reads invertor, whose rows are instants -> localNs.
    fr = localNs(fromStr)
    to = localNs(toStr)
    query = "select %s from invertor where time >= %d and time < %d and deviceNumber = '%s'" % (
            ",".join(columns), fr, to, invertor)
    logging.debug(query)
    return client.query(query)


def localDays(index):
    """Local calendar day for each row of a UTC DatetimeIndex."""
    return index.tz_convert(LOCAL).date


def getBatteryPower(fromStr, toStr):
    """Net battery power per minute from the BMS shunts, in W (+ = charging).

    Returns a Series indexed in UTC, or None when the whole bank is not
    covered — a sum that is missing a pack is not the bank's power, and
    guessing which one is absent is worse than falling back to the inverter.
    """
    try:
        meta = InfluxDBClient(
                config['InfluxDb']['Host'], int(config['InfluxDb']['Port']),
                config['InfluxDb']['User'], config['InfluxDb']['Password'],
                config['InfluxDb']['Db'])
        packs = sorted(m["name"] for m in meta.get_list_measurements()
                       if m["name"].startswith("bms_") and m["name"] != "bms_probe")
    except Exception as e:
        logging.info("BMS discovery failed (%s) — battery energy from the inverter", e)
        return None

    if len(packs) < BMS_MIN_PACKS:
        logging.info("Only %d BMS packs known — battery energy from the inverter",
                     len(packs))
        return None

    fr = localNs(fromStr)
    to = localNs(toStr)
    series = []
    for m in packs:
        q = ('select mean(power_w) as p from "%s" where time >= %d and time < %d '
             'group by time(1m) fill(none)' % (m, fr, to))
        try:
            res = client.query(q)[m]["p"].rename(m)
        except (KeyError, IndexError):
            logging.info("No BMS rows for %s — battery energy from the inverter", m)
            return None
        series.append(res)

    # One bus, N shunts: the pack powers add. ffill covers the jitter of six
    # independent modules landing either side of a minute boundary; dropna
    # then keeps only the minutes where the whole bank is accounted for.
    df = pd.concat(series, axis=1).ffill(limit=2).dropna()
    if df.empty:
        return None

    return df.sum(axis=1)                     # + into the pack


def reportingUnits(fromStr, toStr):
    """Which inverters actually produced rows in the window."""
    fr = localNs(fromStr)
    to = localNs(toStr)
    units = []
    for invertor in ("first", "second"):
        q = ("select count(outputPowerActive) from invertor where time >= %d "
             "and time < %d and deviceNumber = '%s'" % (fr, to, invertor))
        try:
            if not client.query(q)["invertor"].empty:
                units.append(invertor)
        except KeyError:
            continue
    return units


if mode == "daily":

    # Nothing is deleted up front. A rolled-up row is keyed by (day label,
    # devNumber), so writing it again simply overwrites it — whereas delete
    # first, write a second later left invertor_daily with NO row for today
    # for ~0.3 s of every minute (measured 2026-10-27, this runs from cron
    # every minute). Anything that read in that window — the daemon's 24 h
    # summary, the 13-day chart in mqtt.feeder — got an empty answer and the
    # whole "Today" block went blank. Only a unit that has stopped reporting
    # needs its stale row removed, and that is done below, after the write.

    # Battery energy from the shunts. It measures the bank, not a unit, so it
    # can only be attributed when a single inverter is on the bus — with the
    # parallel pair both rows would carry the whole bank and every consumer
    # sums across units.
    units = reportingUnits(dayPast, day)
    bmsPower = getBatteryPower(dayPast, day) if len(units) == 1 else None
    if len(units) > 1:
        logging.info("%d units reporting — battery energy from the inverter", len(units))

    written = []
    for invertor in ["first", "second"]:
        logging.info("Aggregate %s data for %s, %s" % (mode, dayPast, invertor))
        df = getDailyRows(dayPast, day, invertor, columns = columns)

        try:
            df = df["invertor"].reset_index()
        except KeyError:
            # No rows for this unit on this day. Since 2026-10-23 that is the
            # normal state of "first" — the parallel pair became a single unit
            # — and the KeyError aborted the whole run before "second" was ever
            # aggregated. invertor_daily then held no row for today, the daemon's
            # 24 h summary query came back empty, and the mobile page's "Today"
            # block rendered NaN for every line. A missing unit is expected now;
            # skip it and carry on.
            logging.info("No rows for %s on %s — skipping", invertor, dayPast)
            continue
        df["batteryPowerIn"] = df["batteryCurrent"] * df["batteryVoltage"]
        df["batteryPowerOut"] = df["batteryDischargeCurrent"] * df["batteryVoltage"]
        # current x voltage is the whole array only where the unit reports
        # every tracker. The 10 kW Easun reports one of two, so since
        # 2026-10-23 the publisher also sends solarPowerTotal, rebuilt from
        # the energy balance. Prefer it and fall back to the product, which
        # keeps the old parallel pair's history (where the product was right)
        # intact instead of rewriting it.
        product = df["solarCurrent"] * df["solarVoltage"]
        if "solarPowerTotal" in df.columns:
            df["solarPowerIn"] = df["solarPowerTotal"].fillna(product)
        else:
            df["solarPowerIn"] = product
        # The calendar day is local; the hour bucket is a UTC instant. Using
        # the local hour NUMBER would fold the repeated 02:00 of a
        # clocks-back day into one bucket and lose an hour of energy, and
        # using the UTC date would label the day wrong — each needs its own
        # answer, which is the whole point of localNs/stampNs above.
        # Net battery power per minute, from the shunts where we have them.
        # Whatever is missing there keeps the inverter's own figure rather
        # than a hole, so one unreachable module does not erase an hour.
        bat = df["batteryPowerIn"] - df["batteryPowerOut"]
        if bmsPower is not None:
            aligned = bmsPower.reindex(pd.DatetimeIndex(df["index"]),
                                       method="nearest",
                                       tolerance=pd.Timedelta("90s"))
            bat = pd.Series(aligned.values, index=df.index).fillna(bat)
            df["batteryPowerIn"]  = bat.clip(lower=0)
            df["batteryPowerOut"] = (-bat).clip(lower=0)

        # What came off the grid. There is no meter on the supply, so this is
        # the house's energy balance closed from the other side: whatever the
        # load took that neither PV nor the battery provided had to come in
        # from outside.
        #
        #     grid = load + into_battery - PV        (never below zero)
        #
        # It reads correctly in both modes without being told which one it is
        # in. Inverting off the battery, the three terms already balance and
        # the result clips to zero. Sitting on the grid, PV is reconstructed
        # as the charge current over the MPPT efficiency, so the expression
        # collapses to the load plus the charger's own losses — and at night,
        # where solarPowerTotal is held at zero below DARK_BELOW_V, it
        # collapses to the load plus the trickle the unit insists on putting
        # into the battery while it is connected.
        #
        # It assumes the whole house sits behind the inverter, which it does
        # — one breaker, nothing upstream of it.
        #
        # ⚠ Clip LAST, and only after the hourly mean. Clipping each minute
        # rectifies the noise: the three terms are large and come from
        # different instruments, so the residual of a balanced system is not
        # zero but zero ± a few hundred watts, and keeping only the positive
        # half manufactures a daily total out of nothing. Measured on
        # 2026-10-27, a day with the grid breaker physically open: the honest
        # balance came to -3.83 kWh (i.e. the conversion losses), 13 % of
        # minutes still landed positive on transients, and this line reported
        # **1.35 kWh imported from a disconnected grid**. Averaging the hour
        # first lets those transients cancel against their own negative half.
        df["gridPowerIn"] = df["outputPowerActive"] + bat - df["solarPowerIn"]
        # And where the grid is not carrying the house, import is not
        # estimated, it is zero. That is the one hard fact available here; the
        # balance is an inference, so let the fact win.
        #
        # ⚠ Mains *present* is not the same as mains *in use*, and until
        # 2026-10-29 this line conflated them. The breaker was closed again on
        # 10-28 at 16:00 CET while the unit stayed in battery mode all day, so
        # every watt of the system's own conversion loss — the 200 W + 3 % of
        # load measured over the nights of 10-26/27 — was booked as import. It
        # showed up twice: "1.3 kWh from the grid" on a day nothing was drawn,
        # and the panel's loss figure blanking to "síť" at the same moment.
        #
        # The mode is not stored, but it is visible without a new column. The
        # unit regulates its own output to a flat 230.0 V and bypasses the
        # mains untouched, so in bypass outputVoltage *equals* gridVoltage to
        # two decimals while inverting it sits pinned at 230 against a grid
        # that drifts. 2026-10-24, across the PBDV change that ended a bypass
        # at 00:42: 239.42/239.42, 237.94/237.94, 238.72/238.72, then
        # 240.42/230.03, 241.44/230.01, 241.53/230.01.
        onGrid = ((df["gridVoltage"] >= GRID_LIVE_V)
                  & ((df["outputVoltage"] - df["gridVoltage"]).abs() < BYPASS_V))
        df.loc[~onGrid, "gridPowerIn"] = 0.0

        # PV the array could have made and did not, because demand ran out.
        # Published since 2026-10-27; absent from every earlier row and from
        # any unit with a single tracker, where 0 is the honest answer rather
        # than a hole that would drop the whole day's column.
        if "solarPowerCurtailed" not in df.columns:
            df["solarPowerCurtailed"] = 0.0
        else:
            df["solarPowerCurtailed"] = df["solarPowerCurtailed"].fillna(0.0)

        df["time"] = localDays(pd.DatetimeIndex(df["index"]))
        df["hour"] = df["index"].dt.floor("h")
    
        di = {
            "time" : df["time"],
            "hour" : df["hour"],
            "outputPowerApparent" : df["outputPowerApparent"],
            "outputPowerActive" : df["outputPowerActive"],
            "solarPowerIn" : df["solarPowerIn"],
            "batteryPowerIn" : df["batteryPowerIn"],
            "batteryPowerOut" : df["batteryPowerOut"],
            "gridPowerIn" : df["gridPowerIn"],
            "solarPowerCurtailed" : df["solarPowerCurtailed"]
        }
        di = pd.DataFrame(di)
        di = di.groupby(["time", "hour"]).mean()
        # See the note above: the clip belongs here, after the hour has had a
        # chance to cancel its own transients, not on the raw minutes.
        di["gridPowerIn"] = di["gridPowerIn"].clip(lower=0)
        di = di.groupby(["time"]).sum().reset_index()
        di["time"] = pd.to_datetime(di['time'])
        di = di.set_index(["time"])
        di["solarPowerIn"] = di["solarPowerIn"].astype(int)
        di["outputPowerApparent"] = di["outputPowerApparent"].astype(int)
        di["outputPowerActive"] = di["outputPowerActive"].astype(int)
        di["batteryPowerIn"] = di["batteryPowerIn"].astype(int)
        di["batteryPowerOut"] = di["batteryPowerOut"].astype(int)
        di["gridPowerIn"] = di["gridPowerIn"].astype(int)
        di["solarPowerCurtailed"] = di["solarPowerCurtailed"].astype(int)
        for ts in di.index:
            logging.info("%s Wh: load=%d pv=%d bat in=%d out=%d grid=%d "
                         "curtailed=%d (%s)",
                         ts.date(), di.at[ts, "outputPowerActive"],
                         di.at[ts, "solarPowerIn"], di.at[ts, "batteryPowerIn"],
                         di.at[ts, "batteryPowerOut"], di.at[ts, "gridPowerIn"],
                         di.at[ts, "solarPowerCurtailed"],
                         "bms" if bmsPower is not None else "invertor")
   
        #print (di)
        client.write_points(di, 'invertor_daily', tags = {"devNumber" : invertor}, protocol = 'line')
        written.append(invertor)
        logging.info("Done .... %s" % invertor)

    # A unit that reported earlier in the day and has since gone quiet keeps
    # its row, and an overwrite cannot clear what is no longer written. Drop
    # those, and only those — never the row that was just rebuilt.
    for invertor in [u for u in ("first", "second") if u not in written]:
        dropDailyRows(dayPast, day, invertor)


if mode == "monthly":
    logging.info("Aggregate %s data for %s" % (mode, month))
    df = getMonthlyRows('%s-01' % month, nextMonth, columns = [
            "sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut, sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn, sum(gridPowerIn) as gridPowerIn, sum(solarPowerCurtailed) as solarPowerCurtailed"])
    dropMonthlyRows(month)
    dm = df["invertor_daily"] / 1000
    # Stamp the row at the month's label rather than letting it inherit the
    # query's lower bound. That inheritance is what wrote October twice, once
    # at 2026-10-01T00:00Z and once an hour earlier at 2026-09-30T23:00Z.
    dm.index = pd.DatetimeIndex([pd.Timestamp("%s-01" % month)] * len(dm))
    client.write_points(dm, 'invertor_monthly', protocol = 'line')
    logging.info("Done ....")

