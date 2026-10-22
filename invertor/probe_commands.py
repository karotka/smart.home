#!/usr/bin/env python3
"""Sweep the Voltronic query set and print whatever the inverter answers.

Written because a single NAK on QPIGS2 is not evidence that a dual-MPPT unit
keeps its second string to itself. Different firmwares expose PV2 under
different names — QPIGS2, a longer QPIGS, Q1, a per-tracker QPIGSn — and the
only way to know which applies to the unit in front of you is to ask it.

Everything here is a Q-command, i.e. a read. No P-command (a write) is in
the list, so this cannot change a setting.

    sudo systemctl stop invertor-second
    python3 probe_commands.py --port /dev/serial/by-id/usb-1a86_*
    sudo systemctl start invertor-second

Run it in daylight if you can: at night every PV field is zero and a frame
carrying two strings looks exactly like a frame carrying one.
"""

import argparse
import glob
import sys
import time

import serial

from crc16pure import crc16xmodem


COMMANDS = [
    # identity / protocol
    "QPI", "QID", "QSID", "QVFW", "QVFW2", "QVFW3",
    # live values — the ones that might carry a second tracker
    "QPIGS", "QPIGS1", "QPIGS2", "QPIGS3", "QP2GS", "Q1", "QALL",
    # ratings and settings
    "QPIRI", "QPIRI2", "QDI", "QFLAG", "QOPM", "QMOD", "QPIWS",
    # charging limits
    "QMCHGCR", "QMUCHGCR",
    # mppt / tracker specific
    "QMPPTT", "QPVIPGS", "QPIGS0",
    # energy counters — some firmwares split these per tracker
    "QET", "QLT", "QBEQI",
    # parallel
    "QPGS0", "QPGS1",
]


def framed(payload):
    b = payload.encode()
    return b + crc16xmodem(b).to_bytes(2, "big") + b"\r"


def ask(ser, cmd, attempts=2, wait=5.0):
    for _ in range(attempts):
        ser.reset_input_buffer()
        ser.write(framed(cmd))
        out = bytearray()
        deadline = time.time() + wait
        while time.time() < deadline:
            ch = ser.read(1)
            if not ch:
                continue
            if ch == b"\r":
                break
            out += ch
        if out:
            return bytes(out)
        time.sleep(0.3)
    return b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=2400)
    args = ap.parse_args()

    port = args.port
    if "*" in port:
        hits = sorted(glob.glob(port))
        if len(hits) != 1:
            sys.exit("port glob matched %d: %s" % (len(hits), hits))
        port = hits[0]

    ser = serial.Serial(port=port, baudrate=args.baud, timeout=2)
    answered = []
    try:
        for cmd in COMMANDS:
            raw = ask(ser, cmd)
            txt = raw.decode("utf-8", "replace").lstrip("(").rstrip()
            if not raw:
                state = "ticho"
            elif txt.startswith("NAK"):
                state = "NAK"
            else:
                state = "OK"
                answered.append((cmd, txt))
            print("  %-9s %-6s %s" % (cmd, state, txt[:160] if state == "OK" else ""))
    finally:
        ser.close()

    print("\n══ odpovedely, rozlozene na pole ══")
    for cmd, txt in answered:
        parts = txt.split(" ")
        print("\n%s  (%d poli)" % (cmd, len(parts)))
        print("   " + "  ".join("%d:%s" % (i, p) for i, p in enumerate(parts)))


if __name__ == "__main__":
    main()
