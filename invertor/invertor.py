#!/usr/bin/python
"""Invertor monitor — reads a PIP-series inverter over RS232,
writes per-second live data + per-minute aggregates to InfluxDB,
mirrors a live snapshot to Redis for the web UI."""

import glob
import os
import sys
import time
import json
import logging
import signal
import threading
import configparser
from datetime import datetime
from zoneinfo import ZoneInfo
from logging.handlers import RotatingFileHandler

import serial
import paho.mqtt.client as mqtt_client
from influxdb import InfluxDBClient
from crc16pure import crc16xmodem


QID   = b'QID\x18\x0b\r'
QMOD  = b'QMODI\xc1\r'
QPIGS = b'QPIGS\xb7\xa9\r'
QPIRI = b'QPIRI\xf8T\r'

# Fields returned by QPIGS, in protocol order. Used both for parsing the
# response and for building the row sent to InfluxDB / Redis.
QPIGS_FIELDS = [
    "gridVoltage", "gridFreq", "outputVoltage", "outputFreq",
    "outputPowerApparent", "outputPowerActive", "loadPercent", "busVoltage",
    "batteryVoltage", "batteryCurrent", "batteryCapacity", "temperature",
    "solarCurrent", "solarVoltage", "batteryVoltageSCC", "batteryDischargeCurrent",
]

# QPIGS does not stop at field 15. The standard frame runs to 21 fields and we
# were parsing the first 16 and dropping the rest on the floor — for months,
# while hunting a command that would reveal the second MPPT. Field 19 is the
# inverter's own PV power in watts, which is not solarCurrent x solarVoltage
# and may well cover both trackers. Index -> name, numeric fields only; 16 and
# 20 are bit strings and 18 is a version, none of which belong in a float
# series, and the last field carries the frame CRC glued to it.
QPIGS_EXTRA_FIELDS = {
    19: "pvChargingPower",
}

# --- the second tracker, over Modbus on the same wire -----------------------
#
# PI30 carries one PV voltage and one PV current, so the second string was
# reconstructed from the energy balance for months. It does not have to be.
# This unit answers QMN with `VMII-NXPW5KW9` -- the Daxtromn / PowMr VM II
# family -- and those also speak **Modbus RTU as slave 5 on this very RS232
# port, at the same 2400 Bd**. Both trackers are plain holding registers
# there. Register numbers from softwarecrash/Solar2MQTT PR #25, confirmed
# against our own unit on 2026-10-26 at night with the array dark:
#
#     4504 PV1 44.7 V   4505 PV1 0 W
#     4563 PV2 44.0 V   4564 PV2 4 W
#
# Two idle voltages that differ, from one cable, with no extra hardware.
#
# Two traps. Registers hold their bytes **little-endian**, which is not what
# Modbus normally does -- 0xB901 read the usual way is 47361, read swapped it
# is 441, i.e. 44.1 V. And function 4 (read input registers) is rejected;
# function 3 is the one that answers.
MODBUS_UNIT      = 5
MODBUS_MPPT      = {"mppt1": 4504, "mppt2": 4563}   # each: [voltage, power]
MODBUS_POLL_S    = 30      # the trackers move slowly; keep the line free
MODBUS_GIVE_UP   = 20      # consecutive failures before we stop asking
MPPT_STALE_S     = 120     # a measured sum older than this stops outranking the balance
MPPT_FIELDS = ("mppt1Voltage", "mppt1Power",
               "mppt2Voltage", "mppt2Power", "mpptPowerTotal")

# Below this a tracker is dark or barely awake and the difference between the
# two says nothing about curtailment.
CURTAIL_MIN_W = 100

# Efficiencies used to turn the power flows we can measure back into PV input,
# for the tracker this unit does not report. Deliberately coarse: the job is to
# recover a missing half of the array, not to meter to the watt.
MPPT_EFFICIENCY = 0.97       # PV -> battery, through the charge controller
INVERTER_EFFICIENCY = 0.92   # DC bus -> AC output
DARK_BELOW_V = 50            # string volts under which it is simply night

# QPIWS warning/fault bit-field meanings (Axpert/MPP family, best-effort — the raw
# bitstring is always logged too so it can be re-decoded if a bit differs by firmware).
WARN_BITS = {
    1: "Inverter fault", 2: "Bus over", 3: "Bus under", 4: "Bus soft fail",
    # 5: "Line fail" — omitted: grid is intentionally disconnected (off-grid), so
    # this bit is permanently set and would be a constant false alarm.
    6: "OPV short", 7: "Inverter volt low", 8: "Inverter volt high",
    9: "Over temperature", 10: "Fan locked", 11: "Battery volt high",
    12: "Battery low alarm", 14: "Battery under shutdown", 16: "Overload",
    17: "EEPROM fault", 18: "Inverter over current", 19: "Inverter soft fail",
    20: "Self test fail", 21: "OP DC volt over", 22: "Battery open",
    23: "Current sensor fail", 24: "Battery short", 25: "Power limit",
    26: "PV volt high", 27: "MPPT overload fault", 28: "MPPT overload warning",
    29: "Battery too low to charge",
}

# Per-device configuration. Serial port falls back to /dev/ttyUSB0 when the
# preferred port is missing (hosts with a single USB-serial adapter).
DEVICE_CONFIG = {
    'first':  {'port': '/dev/ttyUSB0'},
    'second': {'port': '/dev/ttyUSB1'},
    'third':  {'port': '/dev/ttyUSB2'},
    'fourth': {'port': '/dev/ttyUSB3'},
    'proto':  {'port': '/dev/ttyUSB0'},
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# How many times getGeneralStatus() may retry an unanswered QPIRI before it
# gives up. It used to recurse without a limit.
QPIRI_MAX_RETRIES = 5

# Hard liveness deadline, in seconds. If no QPIGS frame has been parsed within
# this long, the process kills itself so systemd can restart it and
# ExecStartPre can re-enumerate the adapter. Implemented with SIGALRM rather
# than a counter because the failure we are guarding against is a *blocked*
# read on a USB device that went away: pyserial's timeout does not cover
# surprise removal, the loop simply never comes back, and every counter in
# this file stops being incremented. A signal fires anyway.
# 300 s is ~100 missed reads — far beyond any normal hiccup, well under the
# six and a half hours it actually sat there on 2026-10-23.
WATCHDOG_SECONDS = 300

# The inverter's adapter is a CH340 (1a86:7523) and udev gives it a stable
# name under /dev/serial/by-id. Prefer that over the ttyUSBn above.
CH340_BY_ID = '/dev/serial/by-id/usb-1a86_*'


def resolveSerialPort(position):
    """Find the inverter's adapter by identity rather than enumeration order.

    /dev/ttyUSBn is handed out in the order devices appear, so plugging any
    other USB-serial device into the Pi silently renames the inverter's
    adapter. That is exactly what happened on 2026-10-20 19:55: a temperature
    sensor powered from the Pi's USB came up as ttyUSB0 and pushed the
    inverter to ttyUSB1. The daemon went on opening ttyUSB0 for twelve hours,
    logging `ERROR data: <['']>` — indistinguishable from the old CH341 wedge,
    and with the port *opening* successfully there was nothing to retry its
    way out of. The by-id name would have survived it.

    Only used when exactly one CH340 is present: a host with two inverters
    cannot tell them apart this way, so there we keep the fixed names.
    """
    byid = sorted(glob.glob(CH340_BY_ID))
    if len(byid) == 1:
        return byid[0]
    port = DEVICE_CONFIG[position]['port']
    if os.path.exists(port):
        return port
    # Nothing left to guess with. The old code fell back to /dev/ttyUSB0 here,
    # which on a single-inverter host is NOT the inverter — on .225 it is the
    # FTDI temperature board. On 2026-10-23 the CH340 vanished from USB at
    # 19:26 and the daemon spent the next six and a half hours politely talking
    # to a thermometer: the port opened, so nothing retried, nothing failed,
    # and systemd saw a healthy service. Refusing to start is strictly better —
    # systemd restarts us, ExecStartPre re-enumerates the adapter, and the
    # failure is visible in `systemctl status` instead of being invisible.
    raise IOError(
        "no CH340 adapter found (%s) and %s does not exist — refusing to open "
        "an arbitrary tty" % (CH340_BY_ID, port))


def parseChargeStages(s):
    """Parse 'V1:A1, V2:A2, ...' into [(voltage, current), ...] sorted high→low."""
    pairs = []
    for part in s.split(','):
        v, a = part.strip().split(':')
        pairs.append((float(v), int(a)))
    pairs.sort(key=lambda p: -p[0])
    return pairs


def crc16(data):
    return crc16xmodem(data).to_bytes(2, 'big')



class BankMonitor:
    """Live battery-bank power from the BMS shunts, and the grid trickle.

    The inverter's own battery current cannot carry the PV reconstruction in
    mode L. Measured 2026-10-25 23:00, grid, array at 0 V: QPIGS reported
    **exactly 2.00 A** for four hours — which is `mainsMaxChargingCurrent`,
    the setting, not a measurement — while all six BMS packs independently
    measured +6.24 A, split between them in proportion to their capacity
    (1.74 A into the 135 Ah pack, 0.46 A into the 70 Ah one). Same effect
    recorded on 2026-10-24 at 6.6 A. So in mode L the balance was reading
    the charger's configuration back to itself.

    The second thing this fixes is subtler. In mode L every watt into the
    battery was assumed to come from PV, but this unit charges from the grid
    at ~315 W and **cannot be told not to**: `QMUCHGCR` offers
    `002 010 020 ...`, 2 A is already the floor, and charger priority OSO
    does not stop it either (CLAUDE.md). Those watts were being published as
    sunshine — at 05:00 today `solarPowerTotal` read 128 W with the array
    making 2 W.

    So the trickle is measured instead of assumed: at night, in mode L, the
    pack has no other source, and whatever it is taking *is* the grid. That
    value is averaged with a long time constant and subtracted during the
    day. It is a first-order correction — the charger tapers as the pack
    fills, so a value learned at 50 V is only approximately right at 51 V —
    and it stops being a guess entirely once the Modbus grid meter is in
    (see `gridmeter/`).
    """
    TOPIC      = "home/bms/+/snapshot"
    PACKS      = 6          # 5 NMC + the LFP. A partial sum is not the bank.
    MAX_AGE_S  = 30
    # ~1000 s time constant at 1 Hz: long enough to ignore the pack-switching
    # jitter, short enough to follow the taper across one night.
    ALPHA      = 0.001
    STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "grid_trickle.json")

    def __init__(self):
        self._packs = {}
        self._lock = threading.Lock()
        self._trickle = None
        self._trickleVolt = None
        self._client = None
        self._load()

    # -- persistence --------------------------------------------------
    def _load(self):
        """Survive a restart. Without this every Pi reboot in daylight
        would run until the following night with no correction at all."""
        try:
            with open(self.STATE_PATH) as f:
                d = json.load(f)
            self._trickle = float(d["trickle_w"])
            self._trickleVolt = d.get("volt")
            logging.info("grid trickle restored: %.0f W (learned at %s V)",
                         self._trickle, self._trickleVolt)
        except Exception:
            pass

    def _save(self):
        try:
            tmp = self.STATE_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"trickle_w": round(self._trickle, 1),
                           "volt": self._trickleVolt,
                           "updated": datetime.now().isoformat()}, f)
            os.replace(tmp, self.STATE_PATH)
        except Exception as e:
            logging.warning("grid trickle save failed: %s", e)

    # -- MQTT ---------------------------------------------------------
    def start(self, host, port):
        def onConnect(c, u, f, rc):
            c.subscribe(self.TOPIC, qos=0)

        def onMessage(c, u, m):
            try:
                d = json.loads(m.payload)
                pid = d.get("pack_id") or m.topic.split("/")[-2]
                w = d.get("power_w")
                if pid is None or w is None:
                    return
                with self._lock:
                    self._packs[pid] = (time.time(), float(w))
            except Exception:
                pass

        c = mqtt_client.Client("invertor-bank-" + str(os.getpid()))
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        c.on_connect = onConnect
        c.on_message = onMessage
        try:
            c.connect(host, port, keepalive=60)
        except Exception as e:
            logging.warning("BankMonitor MQTT connect failed: %s", e)
        c.loop_start()
        self._client = c

    # -- readings -----------------------------------------------------
    def power(self):
        """Bank power [W], + into the battery, or None.

        None when the whole bank is not reporting. Callers must treat that
        as "don't know": a sum that is missing a pack is not the bank's
        power, and which pack is missing cannot be guessed.
        """
        now = time.time()
        with self._lock:
            fresh = [w for ts, w in self._packs.values()
                     if now - ts <= self.MAX_AGE_S]
        if len(fresh) < self.PACKS:
            return None
        return sum(fresh)

    def trickle(self):
        """Grid charging to subtract in mode L [W]. 0.0 until measured."""
        return self._trickle or 0.0

    def learn(self, bank, volt):
        """Fold one dark, mode-L sample into the trickle average."""
        if bank is None or bank <= 0:
            return
        if self._trickle is None:
            self._trickle = bank
        else:
            self._trickle += self.ALPHA * (bank - self._trickle)
        self._trickleVolt = round(float(volt), 2)
        # Once a minute is plenty for a value with a 1000 s time constant.
        if int(time.time()) % 60 == 0:
            self._save()


BANK = BankMonitor()


class GeneralStatus:
    """Bag of QPIRI-derived inverter config fields."""
    pass


class Invertor:
    """RS232 driver for the PIP-series inverter."""

    def __init__(self, position, chargeStages, chargeDefault, chargeEnabled=True):
        self.position = position
        self.chargeStages = chargeStages
        self.chargeDefault = chargeDefault
        self.chargeEnabled = chargeEnabled
        self.deviceNumber = position
        self.workingStatus = ""
        self.warning = None
        self.warningRaw = ""
        self.warningActive = []
        self._lastChargeCurrent = None   # cache: only write MNCHGC on change (EEPROM wear)
        self._lastWarnPoll = 0.0         # throttle QPIWS polling (~30 s)
        for name in QPIGS_FIELDS:
            setattr(self, name, 0)
        for name in QPIGS_EXTRA_FIELDS.values():
            setattr(self, name, 0.0)
        self._lastRawFrame = None
        self._lastMpptPoll = 0.0
        self._lastMpptOk = 0.0
        self._mpptFails = 0
        for name in MPPT_FIELDS:
            setattr(self, name, 0.0)
        self.gs = GeneralStatus()
        self._open()

    def _open(self):
        port = resolveSerialPort(self.position)
        self.serial = serial.Serial(
            port=port, baudrate=2400,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=2,   # read timeout: never block forever if the inverter goes
                         # silent (e.g. still booting after a power cut) — call()
                         # then returns [''] and the caller reconnects + retries.
        )
        self.serial.flushInput()
        self.serial.flushOutput()
        logging.info(f"Open serial: <{self.serial}>")

    def reconnect(self):
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(1)
        self._open()

    def call(self, length):
        data = []
        start = time.time()
        while True:
            line = self.serial.read(1)
            if not line:                       # read timeout — inverter silent
                self.reconnect()
                return ['']
            if line == b'\r':                  # end of frame
                joined = "".join(data)
                fields = joined[1:length].split(" ")   # drop leading '(' as before
                if not fields or not fields[0]:
                    self.reconnect()
                return fields
            data.append(line.decode('utf-8', 'ignore'))
            if time.time() - start > 6:        # hard deadline — never loop forever
                self.reconnect()
                return ['']

    def refreshData(self):
        self.deviceNumber = self.position
        self.serial.write(QMOD)
        self.workingStatus = self.call(2)[0]
        self.serial.write(QPIGS)
        data = self.call(117)
        if len(data) < len(QPIGS_FIELDS):
            # short/empty frame (timeout, garbage, inverter not ready) — skip this
            # cycle; the caller retries. Prevents an IndexError that would kill the loop.
            raise IOError("short QPIGS response (%d fields)" % len(data))
        for i, name in enumerate(QPIGS_FIELDS):
            setattr(self, name, data[i])
        # Anything past field 15 is best-effort: a firmware that sends a short
        # frame is not an error, it just has nothing to say here.
        for idx, name in QPIGS_EXTRA_FIELDS.items():
            value = 0.0
            if idx < len(data):
                try:
                    value = float(data[idx])
                except (TypeError, ValueError):
                    value = 0.0
            setattr(self, name, value)
        if self._lastRawFrame != data[16:]:
            self._lastRawFrame = data[16:]
            logging.info("QPIGS tail (fields 16+): %s", data[16:])
        # QPIWS: query the warning/fault bit-field so a trip leaves a trace. Throttled
        # to ~30 s (the fault persists ~90 s before a blackout, so 30 s still catches it)
        # to keep the serial light and avoid any chance of aggravating the inverters.
        now = time.time()
        if now - self._lastWarnPoll >= 30:
            self._lastWarnPoll = now
            try:
                self.serial.write(b'QPIWS' + crc16(b'QPIWS') + b'\r')
                w = self.call(40)
                self.warningRaw = w[0] if (w and w[0]) else ""
                self.warningActive = [n for i, n in WARN_BITS.items()
                                      if i < len(self.warningRaw) and self.warningRaw[i] == '1']
            except Exception as e:
                logging.warning(f"QPIWS read failed: {e}")
                self.warningRaw, self.warningActive = "", []
        # Last, and on its own terms: the Modbus side of the line. It is
        # throttled and swallows its own errors, so a bad read here cannot
        # cost us a QPIGS cycle.
        self.readMppt()

    def _modbusRead(self, address, count=2):
        """One function-3 read, little-endian words, or None.

        Deliberately standalone: it does not go through call(), because a
        Modbus reply is a counted binary frame while call() reads ASCII up to
        a carriage return. Keeping the two readers apart is what makes
        interleaving them on one port safe.
        """
        req = bytes([MODBUS_UNIT, 3]) + address.to_bytes(2, "big") + count.to_bytes(2, "big")
        crc = 0xFFFF
        for b in req:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        self.serial.reset_input_buffer()
        self.serial.write(req + crc.to_bytes(2, "little"))
        self.serial.flush()
        reply = self.serial.read(5 + 2 * count)
        if len(reply) < 5 or reply[0] != MODBUS_UNIT or reply[1] != 3:
            return None
        payload = reply[3:3 + reply[2]]
        if len(payload) < 2 * count:
            return None
        return [int.from_bytes(payload[i:i + 2], "little")
                for i in range(0, len(payload), 2)]

    def readMppt(self):
        """Per-tracker PV voltage and power, best-effort.

        Never raises, and never costs the PI30 poll a cycle: on failure the
        previous values stand, and after MODBUS_GIVE_UP consecutive failures
        it stops asking until the process restarts. QPIGS outranks this.
        """
        if self._mpptFails >= MODBUS_GIVE_UP:
            return
        now = time.time()
        if now - self._lastMpptPoll < MODBUS_POLL_S:
            return
        self._lastMpptPoll = now
        try:
            got = {}
            for name, address in MODBUS_MPPT.items():
                regs = self._modbusRead(address)
                if regs is None:
                    raise IOError("no reply from register %d" % address)
                got[name] = regs
            for name, (volt10, watts) in got.items():
                setattr(self, name + "Voltage", round(volt10 / 10.0, 1))
                setattr(self, name + "Power", float(watts))
            self.mpptPowerTotal = float(self.mppt1Power + self.mppt2Power)
            self._lastMpptOk = now
            self._mpptFails = 0
        except Exception as e:
            self._mpptFails += 1
            if self._mpptFails in (1, MODBUS_GIVE_UP):
                logging.warning("MPPT Modbus read failed (%d): %s", self._mpptFails, e)
        finally:
            # Leave the line as PI30 found it, whatever happened above.
            self.serial.reset_input_buffer()

    def solarPowerTotal(self):
        """Total PV input power [W], including the MPPT the protocol hides.

        Since 2026-10-27 this is the **measured** sum of both trackers over
        Modbus (see readMppt) whenever that read is fresh. The balance
        reconstruction documented below stays as the fallback for a dead or
        stale Modbus link, and is still published beside it as
        solarPowerMeasured's companion so the two can be scored against each
        other.

        This unit has two trackers but QPIGS exposes only one — its LCD
        shows both at different operating points, and under solar-only
        charging the battery visibly takes more than QPIGS reports
        (measured 2026-10-23: 710 W reported against 942 W into the pack).
        No command reaches the second tracker; see CLAUDE.md for the sweep.

        So reconstruct the total from the flows that *are* complete:

          mode L  the load runs off the grid, so PV shows up only as
                  charge. Two corrections, both measured rather than
                  assumed: the charge comes from the BMS shunts (QPIGS
                  reports the mains-charge *setting* here, see
                  BankMonitor) and the grid's own trickle is subtracted.
          mode B  the unit is inverting, so PV covers the load plus
                  whatever the battery is net-taking — again from the
                  shunts, which read the charge several amps higher than
                  QPIGS does.

        The measured tracker is a hard floor — the estimate can never come
        out below PV we have actually seen. It does *understate* while the
        battery is float-limited, because charging then stops reflecting
        what the array could make. That is a limit of the method rather
        than a bug, and it is exactly why solarPowerMeasured is kept
        beside it instead of being overwritten.
        """
        try:
            measured = float(self.solarCurrent) * float(self.solarVoltage)
            batV = float(self.batteryVoltage)
            charge = batV * float(self.batteryCurrent)
            discharge = batV * float(self.batteryDischargeCurrent)
            mode = self.workingStatus

            bank = BANK.power()

            # At night the balance has a small positive bias (the load/efficiency
            # term does not land exactly on the discharge term), which would
            # otherwise trickle phantom watt-hours into the daily totals all
            # night. No string voltage means no sun, unambiguously.
            if float(self.solarVoltage) < DARK_BELOW_V:
                # Dark and on grid is the one moment the grid trickle stands
                # alone, with nothing else entering the pack. Measure it here
                # so the daytime mode-L branch has something to subtract.
                if mode == "L":
                    BANK.learn(bank, batV)
                return 0.0

            # Measurement outranks reconstruction wherever it is available.
            # Settled 2026-10-27 09:24 on a 6.5 kW flow, the one test that
            # separates the two candidates, because at that throughput the
            # unit's own overhead is a tenth of the reading instead of twice
            # it: the BMS shunts measured 113.9 A x 52.66 V = 5998 W into the
            # pack with 541 W at the output, so 6539 W was provably coming out
            # of the array. Register 4505 alone claimed 3702 W -- it cannot be
            # the total, it is tracker 1. The sum claimed 7206 W, i.e. 667 W
            # of loss over the measured flow, which is 9 % across MPPT +
            # charger + idle and is what this class of unit actually loses.
            #
            # Why this beats the balance below in the cases that matter: the
            # balance can only see PV that lands somewhere it can measure, so
            # it understates exactly when the pack is float-limited or the
            # charge current is capped -- the hours when knowing the array's
            # real output is the whole point. The measurement does not care
            # where the power goes.
            #
            # Measured on 2026-10-27, the balance understated tracker 2 by a
            # roughly CONSTANT 300-480 W at every point of the morning — and
            # reported it as flat zero between 07:00 and 07:40 while it was
            # making 300-480 W. A constant error is the signature of a loss
            # term being charged to the derived quantity: tracker 1 is read
            # directly, so the system's own losses had nowhere to land but
            # tracker 2. See doc/modbus-registers.md for the table.
            #
            # Losses are now a thing to measure separately rather than an
            # error term hidden inside the PV figure: 8.4-8.8 % at 6-7 kW,
            # but near 600 W flat all the way down to 800 W of PV, which is
            # not yet explained. No correction factor is applied here — one
            # would only re-hide the thing we just stopped hiding.
            if (self._mpptFails < MODBUS_GIVE_UP
                    and time.time() - self._lastMpptOk < MPPT_STALE_S):
                total = float(self.mpptPowerTotal)
                # Both trackers at zero in daylight means the read is not
                # really working, whatever the error counter says; fall
                # through to the balance rather than publish a dark array.
                if total > 0:
                    return round(max(measured, total), 1)

            # Both branches reconstruct what the ARRAY makes, so both have to
            # undo the charge controller's loss. The DC bus is downstream of
            # the MPPT; dividing only in mode L understated mode B by ~3 %.
            if mode == "L":
                # No usable bank reading means no usable estimate: QPIGS's
                # charge figure in this mode is the charger's own setting
                # echoed back, so falling back to it would publish the grid
                # trickle as sunshine. The visible tracker is the honest
                # floor instead.
                if bank is None:
                    return round(measured, 1)
                est = (bank - BANK.trickle()) / MPPT_EFFICIENCY
            elif mode == "B":
                # Same instrument as mode L wherever the bank is reporting.
                # The inverter's charge figure runs several amps low here too
                # (2026-10-26 07:45: QPIGS 25.0 A, shunts 31.5 A), and that
                # gap is most of the "string 2 reads ~400 W under the LCD"
                # the owner has been seeing. QPIGS stays as the fallback —
                # unlike in mode L it is a measurement there, just a coarse
                # one, and the load term carries the estimate anyway.
                bat = bank if bank is not None else (charge - discharge)
                est = (float(self.outputPowerActive) / INVERTER_EFFICIENCY
                       + bat) / MPPT_EFFICIENCY
            else:
                est = measured
            return round(max(measured, est), 1)
        except Exception as e:
            logging.warning("solarPowerTotal failed, falling back to measured: %s", e)
            try:
                return round(float(self.solarCurrent) * float(self.solarVoltage), 1)
            except Exception:
                return 0.0

    def snapshot(self):
        """Current QPIGS values as {field: float} + deviceNumber."""
        row = {"deviceNumber": self.deviceNumber}
        for f in QPIGS_FIELDS:
            row[f] = float(getattr(self, f))
        # What the one visible tracker reports, and what the array as a
        # whole is doing. They differ on this unit — keep both so the gap
        # stays measurable instead of being quietly averaged away.
        row["solarPowerMeasured"] = round(row["solarCurrent"] * row["solarVoltage"], 1)
        row["solarPowerTotal"] = self.solarPowerTotal()
        for name in QPIGS_EXTRA_FIELDS.values():
            row[name] = float(getattr(self, name, 0) or 0)
        # The real per-tracker figures, kept alongside the reconstruction
        # rather than replacing it: while both are recorded, the balance
        # estimate can be checked against measurement.
        for name in MPPT_FIELDS:
            row[name] = float(getattr(self, name, 0) or 0)
        row["solarPowerCurtailed"] = self.curtailedPower()
        return row

    def curtailedPower(self):
        """PV the array could make and is not making, in watts.

        When demand falls below what the roof offers, this unit does not stop
        at the maximum power point — it walks ONE tracker off it, to the left,
        so that string's voltage collapses while its current stays near Isc.
        The two trackers take turns: measured 2026-10-27 13:25-13:26, with
        30 s between samples,

            mppt1 233 V 3035 W / mppt2 276 V 3440 W
            mppt1 301 V 3886 W / mppt2 304 V 3746 W
            mppt1 314 V 4027 W / mppt2 266 V 3287 W
            mppt1 309 V 3983 W / mppt2 238 V 2939 W

        with both currents pinned at 12.4 and 12.9 A throughout. Shade does
        not alternate between two strings every half minute; the inverter's
        own throttling does.

        The strings are matched — 5161 W against 5146 W at 10:40 the same
        morning, fifteen watts apart — so whichever is still sitting at its
        maximum shows what both could make, and the shortfall is the one that
        has been backed off:

            curtailed = 2 x max(P1, P2) - (P1 + P2) = |P1 - P2|

        Two things this is NOT. It is a LOWER bound, because the leading
        tracker may itself be backed off a little. And it assumes the strings
        really are matched, so a genuinely shaded or faulty string would read
        as permanent curtailment — worth remembering before trusting a figure
        that never returns to zero on a clear day.

        Watch it instead of the charge-current cap. The cap is the wrong
        instrument here: on 2026-10-26 and 10-27 it bound for about twenty
        minutes in total, while this was running at 10-20 % for hours. The
        pack is voltage-limited near full, not current-limited, and the cap
        never sees that.
        """
        try:
            p1 = float(self.mppt1Power)
            p2 = float(self.mppt2Power)
        except Exception:
            return 0.0
        if p1 < CURTAIL_MIN_W or p2 < CURTAIL_MIN_W:
            return 0.0
        return round(abs(p1 - p2), 1)

    def set(self, command, value):
        com = f'{command}{value}'.encode('UTF-8')
        data = com + crc16(com) + b'\r'
        ret = self.serial.write(data)
        return self.call(ret)

    def setChargeCurrent(self, batteryVoltage):
        """Set charge current according to battery voltage (stages from config).
        Only writes MNCHGC when the value actually CHANGES — the old code wrote it
        every minute (~1440×/day) even when unchanged, which hammers the inverter's
        EEPROM. Repeated EEPROM writes wear it out and are the prime suspect for the
        recurring 'EEPROM fault' warning (QPIWS bit 17) that precedes the blackouts.
        With a change-only write, MNCHGC is touched at most a handful of times a day.

        Disabled entirely with `[Charge] enabled = 0`, which is what the 10 kW
        unit needs: it is set to 160 A from its own panel, but QMCHGCR reports
        the protocol can only select 010-080, so anything this writes can only
        take charging *down*. A regulator that cannot reach the current value
        has no business touching it."""
        if not self.chargeEnabled:
            return
        value = self.chargeDefault
        for threshold, amps in self.chargeStages:
            if batteryVoltage > threshold:
                value = amps
                break
        if value == self._lastChargeCurrent:
            return
        v = f"{value}".zfill(4)
        ret = self.set("MNCHGC", v)[0]
        self._lastChargeCurrent = value
        logging.info(
            f"Battery voltage is: {batteryVoltage}. "
            f"Charge current is: {self.gs.solarMaxChargingCurrent}, "
            f"setting charge value to: {value}, {ret}"
        )

    def getGeneralStatus(self, depth=0):
        """Get inverter config via QPIRI."""
        self.serial.write(QPIRI)
        data = self.call(100)

        try:
            self.gs.gridVoltage = float(data[0])
        except (ValueError, IndexError):
            # Was `return self.getGeneralStatus()` — unbounded recursion on a
            # port that answers nothing, and it runs from Monitor.__init__, so
            # the daemon never reached run() and MAX_READ_FAILS never applied.
            # Give up instead and let the caller (and systemd) deal with it.
            logging.info(f"ERROR data: <{data}>")
            self.reconnect()
            if depth >= QPIRI_MAX_RETRIES:
                raise IOError("QPIRI unanswered after %d attempts" % (depth + 1))
            return self.getGeneralStatus(depth + 1)

        self.gs.ratedInputCurrent = float(data[1])
        self.gs.ratedAcOutputVoltage = float(data[2])
        self.gs.ratedAcOutputFrequency = float(data[3])
        self.gs.ratedOutputCurrent = float(data[4])
        self.gs.ratedAcOutputApparentPower = float(data[5])
        self.gs.ratedAcOutputActivePower = float(data[6])
        self.gs.ratedBatteryVoltage = float(data[7])
        self.gs.batteryVoltageMainsSwitchingPoint = float(data[8])
        self.gs.batteryVoltageShutdown = float(data[9])
        self.gs.batteryVoltageFastCharge = float(data[10])
        self.gs.batteryVoltageFloating = float(data[11])

        bt = int(data[12])
        self.gs.batteryType = {0: 'AGM', 1: 'FLD'}.get(bt, 'USE')

        self.gs.mainsMaxChargingCurrent = int(data[13])
        self.gs.solarMaxChargingCurrent = int(data[14])

        self.gs.inputRange = 'ALP' if int(data[15]) == 0 else 'UPS'
        self.gs.loadPowerSourcePriority = {0: 'UTL', 1: 'SOL'}.get(int(data[16]), 'SBU')
        self.gs.chargingSourcePriority = {0: 'CUT', 1: 'CSO', 2: 'SUN'}.get(int(data[17]), 'OSO')

        self.gs.canBeParalleledEuquipment = int(data[18])

        self.gs.parallelMode = {0: 'NP', 1: 'SP', 2: '3P1', 3: '3P2', 4: '3P3'}.get(int(data[21]))

        # QPIRI[22] is the back-to-battery (re-discharge) voltage in volts, with
        # 0 meaning FUL = "wait until fully charged". It is NOT an offset from
        # 48 V: the old `48 + int(...)` turned a perfectly ordinary 52.0 V into
        # 100 V, which read as a sentinel and led to the conclusion that this
        # system waits for a full battery before leaving the grid. It does not —
        # verified 2026-10-21 against the raw frame.
        #
        # Kept as an int, not a float. The setting only takes whole volts
        # (48..58, or 0 for FUL), and InfluxDB fixes a field's type when the
        # field is first written: `invertor_status` already holds this one as
        # an integer, so writing 52.0 made the server reject the *whole point*
        # — "field type conflict … dropped=1" — and every config snapshot was
        # silently lost until this was noticed.
        self.gs.batteryVoltageHighEndInverterSwitching = int(round(float(data[22])))

        self.gs.solarWorkingConditionsParallel = 'ONE' if int(data[23]) == 0 else 'ALL'
        self.gs.automaticAdjustmentSolarMaximumChargingPower = 'ALOAD' if int(data[24]) == 0 else 'BMAX'

        return self.gs


# Not read off the wire — built in snapshot() from the fields that are.
# They have to be averaged into the per-minute measurement as well, or the
# long-term series keeps only the half of the PV this unit chooses to report.
#
# MPPT_FIELDS are deliberately NOT here, and are stripped again before the
# per-second write (see writePerSecond). The owner does not want new columns
# in InfluxDB for something the existing ones can carry: the array total is
# `solarPowerTotal`, tracker 1 is `solarPowerMeasured`/`pvChargingPower`, and
# tracker 2 is the difference. The per-tracker figures stay in the live
# snapshot (Redis + MQTT) where the display wants them and nothing accumulates.
DERIVED_FIELDS = (("solarPowerMeasured", "solarPowerTotal",
                   "solarPowerCurtailed")
                  + tuple(QPIGS_EXTRA_FIELDS.values()))


def averageRows(rows):
    """Mean of QPIGS_FIELDS (+ the derived PV pair) across rows.

    The first row's deviceNumber wins.
    """
    out = {"deviceNumber": rows[0]["deviceNumber"]}
    for f in QPIGS_FIELDS:
        out[f] = round(sum(r[f] for r in rows) / len(rows), 1)
    for f in DERIVED_FIELDS:
        vals = [r[f] for r in rows if f in r]
        if vals:
            out[f] = round(sum(vals) / len(vals), 1)
    return out


class Monitor:
    """Owns the inverter, sinks, and the main loop."""

    def __init__(self, position, config):
        self.position = position
        self.snapshotTopic = "home/invertor/snapshot/" + position
        self.config = config
        self.tz = ZoneInfo(config.get("App", "timezone", fallback="Europe/Prague"))
        self.inv = Invertor(
            position,
            parseChargeStages(config["Charge"]["stages"]),
            int(config["Charge"]["default_current"]),
            config.getboolean("Charge", "enabled", fallback=True),
        )
        self.gsDict = self.inv.getGeneralStatus().__dict__
        self.lastSummary = {}
        self.refreshSummary()
        self._lastWarnRaw = None
        self._lastMode = None
        self.mqtt = self._mqtt()
        # Second, read-only MQTT client: the BMS shunts, which the mode-L
        # PV reconstruction needs because QPIGS cannot supply them.
        BANK.start(self.config["Mqtt"].get("host"),
                   int(self.config["Mqtt"].get("port")))

    def _influx(self):
        cfg = self.config["InfluxDb"]
        return InfluxDBClient(
            cfg["Host"], int(cfg["Port"]),
            cfg["User"], cfg["Password"],
            cfg["Db"],
            timeout=5, retries=2,
        )

    def _mqtt(self):
        """Long-lived MQTT publisher. paho's loop_start runs the network
        thread in the background so publish() returns fast even when the
        broker is briefly unreachable (paho queues + reconnects)."""
        host = self.config["Mqtt"].get("host")
        port = int(self.config["Mqtt"].get("port"))
        c = mqtt_client.Client("invertor-" + self.position)
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            c.connect(host, port, keepalive=60)
        except Exception as e:
            logging.warning("MQTT initial connect failed: %s", e)
        c.loop_start()
        return c

    def _publishSnapshot(self, row):
        """JSON-encode the live snapshot + config + 24h summary and push
        it to MQTT. The bridge re-encodes for the legacy Redis key."""
        payload = dict(self.gsDict)
        payload.update(row)
        payload["workingStatus"] = self.inv.workingStatus
        payload["last"] = self.lastSummary
        # The two inputs behind solarPowerTotal in mode L, published so the
        # reconstruction can be checked against the LCD without a debugger.
        payload["batteryPowerBms"] = BANK.power()
        payload["gridTrickleW"] = round(BANK.trickle(), 1)
        try:
            self.mqtt.publish(self.snapshotTopic,
                              json.dumps(payload, default=str),
                              qos=0, retain=True)
        except Exception as e:
            logging.error("MQTT publish failed: %s", e)

    SUMMARY_QUERY = (
        "select sum(batteryPowerIn) as batteryPowerIn, "
        "sum(batteryPowerOut) as batteryPowerOut, "
        "sum(outputPowerActive) as outputPowerActive, "
        "sum(outputPowerApparent) as outputPowerApparent, "
        "sum(solarPowerIn) as solarPowerIn, "
        "sum(gridPowerIn) as gridPowerIn "
        "from invertor_daily where time > now() - 24h"
    )

    def refreshSummary(self, client=None):
        """The day's roll-up behind the UI's "Today" block.

        Holds the last GOOD answer rather than whatever the last query
        returned, because an empty result here almost never means an empty
        day. Two things produce one:

          * aggregate.py rebuilds invertor_daily every minute and deleted the
            day before writing it back, leaving ~0.3 s a minute with no row
            (measured 2026-10-27). That hole is gone now, but a slow rebuild
            can still widen it;
          * a restart begins with nothing cached — and the CH341 drops
            restarted this daemon 64 times on 2026-10-27, each one blanking
            every line of the block for up to a minute.

        So an empty answer is no news and is ignored. A genuinely empty day
        (the minutes after midnight, before the first roll-up) keeps showing
        yesterday for a moment, which is a far smaller lie than seven dashes.
        """
        try:
            client = client or self._influx()
            points = list(client.query(self.SUMMARY_QUERY).get_points())
        except Exception as e:
            logging.warning("24h summary query failed: %s", e)
            return
        if points and any(v is not None
                          for k, v in points[0].items() if k != "time"):
            self.lastSummary = points[0]

    def writePerSecond(self, row, dt):
        """Live values → InfluxDB invertor_actual + MQTT snapshot.

        InfluxDB gets the long-standing columns only. MQTT gets the whole row,
        per-tracker figures included — those are live diagnostics for the
        display, not a series anyone needs to query back.
        """
        try:
            client = self._influx()
            client.write_points([{
                "measurement": "invertor_actual",
                "time": dt.isoformat(),
                "fields": {k: v for k, v in row.items()
                           if k not in MPPT_FIELDS},
            }])
        except Exception as e:
            logging.error(f"InfluxDB write failed (actual): {e}")
        # MQTT runs even when InfluxDB is down so the UI keeps live data.
        self._publishSnapshot(row)

    def writePerMinute(self, minuteRows, dt):
        """Aggregate, persist long-term, refresh charge regulation + 24h summary."""
        avg = averageRows(minuteRows)

        # Battery regulation runs before InfluxDB so a network hiccup never
        # leaves the inverter on a stale charge current.
        self.gsDict = self.inv.getGeneralStatus().__dict__
        self.inv.setChargeCurrent(avg["batteryVoltage"])

        try:
            client = self._influx()
            # The operating mode belongs in the per-minute series, not only in
            # invertor_status, which is purged after an hour. Without it here,
            # anything reading history has to infer bypass from the fact that
            # output volts equal input volts — true, but an inference, and it
            # breaks the moment the grid happens to sit at the regulated 230.0.
            # L is bypass, B is inverting; the roll-up needs no more than that
            # to know whether a residual is an import or a conversion loss.
            #
            # One sample, taken at the write rather than averaged over the
            # minute: the mode is a state, not a quantity, and it changes twice
            # a night at most, so a minute that straddles a transition is worth
            # less than the complexity of weighting it.
            avg["workingStatus"] = self.inv.workingStatus
            client.write_points([{
                "measurement": "invertor",
                "time": dt.isoformat(),
                "fields": avg,
            }])
            statusFields = dict(self.gsDict)
            statusFields["workingStatus"] = self.inv.workingStatus
            # Stamp the row with the unit it came from. Without this BOTH
            # inverters write unattributable rows into one measurement, so
            # anything reading "the latest status" gets whichever wrote last —
            # and that alternates every minute. It's why a parallel-pair config
            # mismatch (SUB vs SBU, OSO vs SUN, 70 vs 80 A) was invisible in
            # every UI even though the data was being collected all along.
            statusFields["deviceNumber"] = avg["deviceNumber"]
            client.write_points([{
                "measurement": "invertor_status",
                "time": dt.isoformat(),
                "fields": statusFields,
            }])
            # Housekeeping — once a minute is enough (was once a second).
            client.query("delete from invertor_actual where time < now() - 1h")
            client.query("delete from invertor_status where time < now() - 1h")
            # 24h summary for the Redis live tile — also moved out of the
            # per-second hot path.
            self.refreshSummary(client)
            logging.info(f"Send data ok time: {dt}, device number: {avg['deviceNumber']}")
        except Exception as e:
            logging.error(f"InfluxDB write failed (minute): {e}")

    def run(self):
        # The CH341 USB-serial adapter wedges every so often (Errno 5 / "readiness
        # to read but returned no data"). Retrying forever means the process never
        # dies, so systemd never restarts it, so ExecStartPre's usbreset never runs
        # — and we keep republishing the last good frame as if it were live (seen:
        # 1h45m of a frozen 4.6 kW reading). Bail out after this many CONSECUTIVE
        # failures (~2 s apart) and let systemd restart us + re-enumerate the adapter.
        MAX_READ_FAILS = 30
        # A silent inverter and a vanished adapter are different failures. When the
        # CH340 drops off the USB bus pyserial closes the port and every later call
        # raises "port is not open"; no amount of retrying brings it back, only the
        # ExecStartPre re-enumeration does. Sitting out the full MAX_READ_FAILS there
        # costs ~70 s of monitoring per event, and on 2026-10-26 the adapter dropped
        # 34 times between 10:35 and 14:12 — the window where the battery charged at
        # 154 A, i.e. the inverter's own switching noise. Bail out fast in that case.
        MAX_DEVICE_FAILS = 4
        fails = 0
        lastMinute = -1
        minuteRows = []
        while True:
            try:
                dt = datetime.now(self.tz)
                self.inv.refreshData()
                armWatchdog()          # progress: push the deadline out again
                row = self.inv.snapshot()
                self.writePerSecond(row, dt)
                logging.info(f"Send data to invertor actual ok time: {dt}, device number: {row['deviceNumber']}")

                # Black-box fault capture: log inverter warnings/faults on change and any
                # non-normal device mode, so a trip that blacks out the system leaves a trace.
                try:
                    if self.inv.warningRaw != self._lastWarnRaw:
                        if self.inv.warningActive:
                            logging.warning(f"INVERTER FAULT/WARN [{row['deviceNumber']}]: "
                                            f"{', '.join(self.inv.warningActive)} (QPIWS={self.inv.warningRaw})")
                        elif self._lastWarnRaw:
                            logging.info(f"Inverter warnings cleared [{row['deviceNumber']}] "
                                         f"(QPIWS={self.inv.warningRaw})")
                        self._lastWarnRaw = self.inv.warningRaw
                    if self.inv.workingStatus != self._lastMode:
                        if self.inv.workingStatus not in ("B", "L"):
                            logging.warning(f"INVERTER MODE [{row['deviceNumber']}]: {self.inv.workingStatus}")
                        self._lastMode = self.inv.workingStatus
                except Exception as e:
                    logging.warning(f"warning-check failed: {e}")

                minute = dt.minute
                if minute == lastMinute:
                    minuteRows.append(row)
                else:
                    if lastMinute != -1:
                        self.writePerMinute(minuteRows, dt)
                    minuteRows = [row]
                lastMinute = minute
                fails = 0
            # A single bad read (timeout, short/garbage frame, silent inverter after a
            # power cut) must not kill the loop — skip the cycle and retry. SystemExit
            # from the SIGTERM handler is a BaseException, so it passes through to main().
            except Exception as e:
                fails += 1
                # pyserial marks the port closed once the adapter is gone, so is_open
                # tells the two failure modes apart without parsing the message.
                portGone = not getattr(self.inv.serial, "is_open", True)
                logging.warning(f"read cycle failed, retrying: {e}")
                if fails >= (MAX_DEVICE_FAILS if portGone else MAX_READ_FAILS):
                    # SystemExit is a BaseException -> skips this handler and reaches
                    # main()'s finally, so the port is closed cleanly before the restart.
                    logging.error(
                        f"serial wedged: {fails} consecutive read failures "
                        f"({'adapter off the bus' if portGone else 'no usable reply'})"
                        f" — exiting so systemd restarts us and ExecStartPre "
                        f"re-enumerates the adapter")
                    raise SystemExit(1)
                time.sleep(2)


def armWatchdog():
    """(Re)start the liveness deadline. Called after every good read."""
    signal.alarm(WATCHDOG_SECONDS)


def _watchdogFired(signum, frame):
    """Last resort when the main loop stops making progress.

    os._exit, not an exception: the read loop and main() both catch broad
    `except Exception`, so a raised error would be swallowed and counted as
    one more retry — which is precisely the hole this closes. Logging is
    flushed by hand because os._exit skips atexit handlers.
    """
    logging.error("watchdog: no inverter frame for %ds — exiting so systemd "
                  "restarts us and the adapter is re-enumerated",
                  WATCHDOG_SECONDS)
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    os._exit(1)


def createPid(pidfile):
    if os.path.isfile(pidfile):
        print(f"{pidfile} already exists, exiting")
        sys.exit()
    with open(pidfile, 'w') as f:
        f.write(str(os.getpid()))


# Rotation for the daemon log. backupCount alone does nothing — without
# maxBytes the handler defaults to 0, which means "never rotate", so the log
# grew without bound and a cron was added to blank it every night at 01:00.
#
# That cron destroyed the only evidence we have of the thing we are trying to
# catch. The QPIWS black box was added specifically to record what the
# inverters report in the minutes before the recurring outage; both Pis died
# abruptly at ~19:56 on 2026-10-20, and at 01:00 the next morning the log
# holding that window was emptied — hours before anyone looked at it.
#
# 15 MB × 6 files ≈ three days of history at the ~18 MB/day this writes, on a
# card with 2.8 GB free. Rotation also keeps the daemon's own file handle
# valid, which a `mv` from cron would not.
LOG_MAX_BYTES = 15 * 1024 * 1024
LOG_BACKUPS = 5


def createLog(position):
    handler = RotatingFileHandler(
        f"{BASE_DIR}/log/invertor_{position}_log",
        maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S'))
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main():
    position = sys.argv[1]
    pidfile = f"/tmp/invertor_{position}.pid"

    createPid(pidfile)
    createLog(position)

    config = configparser.ConfigParser()
    config.read(f"{BASE_DIR}/conf/config.ini")

    # Armed before Monitor() is constructed, not after: the six-hour silence on
    # 2026-10-23 happened inside __init__, in getGeneralStatus(), so a watchdog
    # that only covered the main loop would have slept through it.
    signal.signal(signal.SIGALRM, _watchdogFired)
    armWatchdog()

    monitor = Monitor(position, config)

    # Clean shutdown: systemd sends SIGTERM on stop/restart. Without a handler
    # Python terminates without running the finally below, so the serial port
    # is never closed — which leaves the USB-serial adapter wedged and the next
    # start stuck in an "ERROR data: <''>" reconnect loop until a full reboot
    # re-enumerates the device. Turning SIGTERM/SIGINT into SystemExit lets the
    # finally run and close the port cleanly, so a plain restart works again.
    def _shutdown(signum, frame):
        logging.info(f"Received signal {signum} — shutting down cleanly")
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        monitor.run()
    except SystemExit:
        pass
    except Exception:
        logging.error("Exception occurred", exc_info=True)
    finally:
        try:
            monitor.inv.serial.close()
            logging.info("Serial port closed cleanly")
        except Exception as e:
            logging.warning(f"Serial close failed: {e}")
        if os.path.isfile(pidfile):
            os.unlink(pidfile)


if __name__ == "__main__":
    main()
