#!/usr/bin/env python3
"""Send one setting command to a PIP inverter over its serial link.

For the handful of settings that are configured once and then left alone —
output source priority (POP), charge voltages (PCVV/PBFT), the back-to-battery
point — where going to the physical panel is the only alternative.

⚠ **Not for anything repetitive.** Every one of these writes goes to the
inverter's EEPROM, and writing on a schedule is what caused the September
outage series: `setChargeCurrent` wrote MNCHGC every minute whether or not the
value had changed, ~1440 writes/day/inverter, until QPIWS started reporting an
EEPROM fault three minutes before each blackout. The daemon now writes only on
a real change; keep it that way, and keep one-shot settings one-shot.

⚠ **Stop the daemon first.** It holds the port open and polls about once a
second; two writers on one tty interleave and both get garbage:

    sudo systemctl stop invertor-second
    python3 send_command.py --port /dev/serial/by-id/usb-1a86_* POP02
    sudo systemctl start invertor-second

In a parallel pair, charge *voltages* propagate from the master to the slave
but the charge *current* does not — so never assume a setting reached both.
Read it back on each unit (this tool prints QPIRI before and after).

Usage:
    python3 send_command.py --port <dev> <COMMAND>      # e.g. POP02
    python3 send_command.py --port <dev> --query        # just show QPIRI
"""

import argparse
import glob
import sys
import time

import serial

from crc16pure import crc16xmodem


# QPIRI field indices, taken from getGeneralStatus() in invertor.py rather
# than from a datasheet — the daemon's parsing is what the rest of the system
# believes, so a tool that disagreed with it would be worse than useless.
QPIRI_LABELS = {
    7:  "ratedBatteryVoltage",
    8:  "batteryVoltageMainsSwitchingPoint",   # back to utility
    9:  "batteryVoltageShutdown",
    10: "batteryVoltageFastCharge",            # bulk
    11: "batteryVoltageFloating",
    13: "mainsMaxChargingCurrent",
    14: "solarMaxChargingCurrent",
    15: "inputRange",                          # 0=ALP(appliance) 1=UPS
    16: "loadPowerSourcePriority",             # 0=UTL 1=SOL 2=SBU
    17: "chargingSourcePriority",              # 0=CUT 1=CSO 2=SUN 3=OSO
    21: "parallelMode",                        # 0=NP 1=SP ...
    22: "batteryRedischargeVoltage",           # back to battery; 00 = FUL
}


def crc16(data):
    return crc16xmodem(data).to_bytes(2, "big")


def readFrame(ser, deadline=6.0):
    """Read one '(...)\\r' frame and return it without the leading '('."""
    out = []
    start = time.time()
    while True:
        ch = ser.read(1)
        if not ch:
            return ""
        if ch == b"\r":
            return "".join(out).lstrip("(")
        out.append(ch.decode("utf-8", "ignore"))
        if time.time() - start > deadline:
            return "".join(out).lstrip("(")


def query(ser, attempts=4):
    """QPIRI, retried — the first request after the daemon releases the port
    very often comes back empty (the adapter has just been reopened and the
    inverter is mid-poll). The daemon papers over this with its own retry
    loop; a one-shot tool has to do it explicitly or it looks like a dead
    link when nothing is wrong."""
    for n in range(attempts):
        ser.flushInput()
        ser.write(b"QPIRI" + crc16(b"QPIRI") + b"\r")
        frame = readFrame(ser)
        fields = frame.split(" ")
        if fields and fields[0]:
            return fields
        time.sleep(1)
    return []


def show(fields, title, raw=False):
    print("  %s:" % title)
    if not fields or not fields[0]:
        print("    (zadna odpoved)")
        return
    for i, label in sorted(QPIRI_LABELS.items()):
        if i < len(fields):
            print("    [%2d] %-36s %s" % (i, label, fields[i]))
    if raw:
        # The whole positional frame, so an index that turns out to be
        # mislabelled can be caught by eye instead of by assumption.
        print("    syrovy ramec:")
        print("      " + " ".join("%d:%s" % (i, f) for i, f in enumerate(fields)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", nargs="?", help="e.g. POP02")
    ap.add_argument("--port", required=True)
    ap.add_argument("--query", action="store_true", help="read QPIRI and exit")
    args = ap.parse_args()

    port = args.port
    if "*" in port:                       # allow a glob, as in the docstring
        matches = sorted(glob.glob(port))
        if len(matches) != 1:
            sys.exit("port glob matched %d devices: %s" % (len(matches), matches))
        port = matches[0]

    ser = serial.Serial(port=port, baudrate=2400,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        bytesize=serial.EIGHTBITS,
                        timeout=2)
    try:
        ser.flushInput()
        ser.flushOutput()
        before = query(ser)
        show(before, "pred", raw=True)

        if args.query or not args.command:
            return

        com = args.command.encode("UTF-8")
        ser.write(com + crc16(com) + b"\r")
        reply = readFrame(ser)
        print("\n  %s -> odpoved: %r  (%s)\n"
              % (args.command, reply,
                 "ACK = prijato" if reply.startswith("ACK")
                 else "NAK = ODMITNUTO" if reply.startswith("NAK")
                 else "necekana odpoved"))

        time.sleep(1)
        after = query(ser)
        show(after, "po")

        if before and after and before != after:
            print("\n  zmenila se pole:")
            for i, (a, b) in enumerate(zip(before, after)):
                if a != b:
                    print("    [%d] %-34s %s -> %s"
                          % (i, QPIRI_LABELS.get(i, ""), a, b))
        elif not args.query:
            print("\n  QPIRI se nezmenilo")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
