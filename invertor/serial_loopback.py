#!/usr/bin/env python3
"""Decide whether a silent serial link is the cable's fault or the device's.

`ERROR data: <['']>` means the port opened and nothing came back, which is
the same symptom for a broken cable, a wrong pinout, a device that is off,
and a device that simply does not speak to us. This separates the cable from
everything else, which is the only split that matters first.

Short the cable's TX and RX together at the far end — the two data pins of
the DB9 — and run this. Whatever it writes must come straight back:

    python3 serial_loopback.py --port /dev/serial/by-id/usb-1a86_*

    ECHO   -> the USB-serial half works end to end. The fault is beyond the
              short: the device, its port, or the wiring between.
    TICHO  -> nothing comes back through the loop, so the cable itself is
              broken. On a converter board that has just been taken apart,
              suspect the solder tabs onto the DB9 first.

Note it proves the path only as far as the short. Looping at the USB plug
would clear the chip but not the wire; loop as close to the far end as the
connector allows.
"""

import argparse
import glob
import sys
import time

import serial


PROBE = b"LOOPBACK-TEST-0123456789"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=2400)
    args = ap.parse_args()

    port = args.port
    if "*" in port:
        hits = sorted(glob.glob(port))
        if len(hits) != 1:
            sys.exit("port glob matched %d devices: %s" % (len(hits), hits))
        port = hits[0]

    ser = serial.Serial(port=port, baudrate=args.baud, timeout=2)
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.2)
        ser.write(PROBE)
        ser.flush()
        # 2400 Bd is ~240 B/s, so 24 bytes need ~0.1 s; a second is generous.
        time.sleep(1.0)
        back = ser.read(len(PROBE))
        print("odeslano: %r" % PROBE)
        print("prislo:   %r" % back)
        if back == PROBE:
            print("\nECHO — kabel je v poradku az ke zkratu.")
            print("Chyba je za nim: zarizeni, jeho port, nebo zapojeni mezi.")
        elif back:
            print("\nCASTECNE (%d z %d bajtu) — spoj drzi, ale je nespolehlivy."
                  % (len(back), len(PROBE)))
            print("Studeny spoj nebo spatny kontakt ve zkratu.")
        else:
            print("\nTICHO — smycka nevraci nic, kabel je preruseny.")
            print("U rozebrane hlavice zacni u pajenych oucek na DB9.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
