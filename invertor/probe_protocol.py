#!/usr/bin/env python3
"""Identify which protocol an inverter speaks, before writing any driver for it.

Voltronic-family units (Axpert, MPP Solar, Easun and the other rebadges) come
in two protocol generations and they are not compatible:

  PI30 — the one invertor.py already speaks. ASCII commands with a CRC16 and
         a trailing CR: QPI, QPIGS, QPIRI, QMOD, QPIWS. Second MPPT, where
         the unit has one, answers QPIGS2.
  PI18 — newer firmware. Commands are length-prefixed and carry a different
         shape: ^P005PI, ^P003GS, ^P003PIRI … Same CRC, different grammar.

Guessing wrong looks exactly like a dead cable, so this asks the unit instead.
Run it once with the new inverter connected and nothing else using the port:

    sudo systemctl stop invertor-first          # if that port is in use
    python3 probe_protocol.py --port /dev/serial/by-id/usb-1a86_*

It only ever *reads*. No command here changes a setting.
"""

import argparse
import glob
import sys
import time

import serial

from crc16pure import crc16xmodem


# (label, command bytes built the PI30 way: payload + crc + CR)
PI30 = [
    ("QPI",     b"QPI"),      # protocol id — the deciding answer
    ("QID",     b"QID"),      # serial number
    ("QVFW",    b"QVFW"),     # firmware version
    ("QMOD",    b"QMOD"),     # device mode
    ("QPIRI",   b"QPIRI"),    # rated/config frame
    ("QPIGS",   b"QPIGS"),    # live values, tracker 1
    ("QPIGS2",  b"QPIGS2"),   # live values, tracker 2 — the two-string case
    ("QPIWS",   b"QPIWS"),    # warning/fault bit field
]

# PI18 uses the same CRC but a ^Pnnn<cmd> envelope, where nnn is the length
# of what follows. Built literally so the difference stays visible.
PI18 = [
    ("^P005PI",   b"^P005PI"),
    ("^P005ID",   b"^P005ID"),
    ("^P006VFW",  b"^P006VFW"),
    ("^P003MOD",  b"^P003MOD"),
    ("^P007PIRI", b"^P007PIRI"),
    ("^P003GS",   b"^P003GS"),
    ("^P005PGS0", b"^P005PGS0"),
    ("^P004FWS",  b"^P004FWS"),
]


def framed(payload):
    return payload + crc16xmodem(payload).to_bytes(2, "big") + b"\r"


def ask(ser, payload, attempts=3, wait=6.0):
    """Send a command and read one frame, patiently and more than once.

    The first version of this waited 1.5 s and tried once, and reported
    silence on a link that the daemon was reading happily a minute either
    side of it — these units do not always answer the first request after
    the port is reopened. Match what invertor.py actually does: a 2 s read
    timeout, a 6 s deadline for the whole frame, and a few goes before
    calling it dead.
    """
    for _ in range(attempts):
        ser.reset_input_buffer()
        ser.write(framed(payload))
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
        time.sleep(0.5)
    return b""


def readable(raw):
    if not raw:
        return "(ticho)"
    txt = raw.decode("utf-8", "replace").lstrip("(")
    if txt.startswith("NAK"):
        return "NAK (prikaz neznamy)"
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=2400,
                    help="2400 is the Voltronic default; newer units are "
                         "sometimes 9600 or 19200 — try those if everything "
                         "comes back silent")
    args = ap.parse_args()

    port = args.port
    if "*" in port:
        hits = sorted(glob.glob(port))
        if len(hits) != 1:
            sys.exit("port glob matched %d devices: %s" % (len(hits), hits))
        port = hits[0]

    print("port %s @ %d Bd\n" % (port, args.baud))
    ser = serial.Serial(port=port, baudrate=args.baud,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        bytesize=serial.EIGHTBITS,
                        timeout=2)
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        scores = {}
        for family, cmds in (("PI30", PI30), ("PI18", PI18)):
            print("══ %s ══" % family)
            good = 0
            for label, payload in cmds:
                raw = ask(ser, payload)
                ans = readable(raw)
                if raw and not ans.startswith("NAK") and ans != "(ticho)":
                    good += 1
                print("  %-10s %s" % (label, ans[:150]))
            scores[family] = good
            print()

        print("══ zaver ══")
        if scores["PI30"] == scores["PI18"] == 0:
            print("  Nic neodpovedelo. Zkus jinou rychlost (--baud 9600 / 19200),")
            print("  jiny kabel, nebo jestli port neblokuje bezici daemon.")
        else:
            best = max(scores, key=scores.get)
            print("  Vypada to na %s  (%s: %d odpovedi, %s: %d)"
                  % (best, "PI30", scores["PI30"], "PI18", scores["PI18"]))
            if best == "PI30":
                print("  -> invertor.py funguje po pridani zarizeni do DEVICE_CONFIG.")
                print("     Pokud QPIGS2 odpovedelo, ma dva MPPT a je potreba")
                print("     secist oba stringy, ne cist jen prvni.")
            else:
                print("  -> potreba doplnit PI18 sadu prikazu do invertor.py;")
                print("     datovy kontrakt (Redis/MQTT/Influx) zustava stejny.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
