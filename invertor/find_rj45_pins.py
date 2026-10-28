#!/usr/bin/env python3
"""Najdi TX a GND na RJ45 hlavici kabelu, do ktereho neni videt.

Kupovane kabely USB->RJ45 pro menice maji prevodnik zality v USB konci a
hlavici bez viditelnych vodicu, takze pinout z nich nezjistis pohledem.
Zjistis ho ale multimetrem, protoze RS232 je na klidu na zaporne urovni:

    TX   v klidu  -5 az -12 V proti signalove zemi
    GND  0 V, prozvoni se na kovovy plast USB konektoru
    RX   vstup, visi kolem 0 V a neprozvoni se

Samotne staticke mereni plete, protoze nekvalitni multimetr ukaze na
plovoucim vstupu cokoliv. Proto tenhle skript s linkou **hybe**: strida
BREAK (linka drzena na opacne, kladne urovni) a klid. Spravny pin je ten,
ktery se pritom houpe mezi -8 V a +8 V. Zadny jiny se nehne.

Postup:

 1. Kabel zapoj do USB, RJ45 nech volny. Menic do toho nijak nevstupuje.
 2. Prozvon ohmmetrem kazdy pin RJ45 proti kovovemu plasti USB konektoru.
    Ten, ktery ma skoro nula ohmu, je GND.
 3. Spust tenhle skript a cernou sondu nech na te zemi. Cervenou projizdej
    piny 1 az 8 a sleduj, ktery se houpe do rytmu vypisu. To je TX menice
    -- tedy pin, na ktery kabel vysila.
 4. RX uz zbyva dohadem: u techhle kabelu to je soused TX. Overis ho tim,
    ze TX a RX zkratis a pustis serial_loopback.py.

    sudo systemctl stop invertor-second
    python3 find_rj45_pins.py --port '/dev/serial/by-id/usb-1a86_*'
    sudo systemctl start invertor-second

Overene zapojeni tehle instalace, pro srovnani s tim, co namerit:

    RJ45 1 -> DB9 2 (RX)    RJ45 2 -> DB9 3 (TX)    RJ45 8 -> DB9 5 (GND)
"""

import argparse
import glob
import sys
import time

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=2400)
    ap.add_argument("--period", type=float, default=4.0,
                    help="jak dlouho drzet kazdy stav, v sekundach")
    ap.add_argument("--cycles", type=int, default=30)
    args = ap.parse_args()

    port = args.port
    if "*" in port:
        hits = sorted(glob.glob(port))
        if len(hits) != 1:
            sys.exit("port glob matched %d devices: %s" % (len(hits), hits))
        port = hits[0]

    ser = serial.Serial(port=port, baudrate=args.baud, timeout=1)
    print("port %s, %d Bd" % (port, args.baud))
    print("cernou sondu na zem (plast USB), cervenou po pinech 1..8.")
    print("Hledas pin, ktery se houpe. Ctrl-C az ho najdes.\n")
    try:
        for i in range(args.cycles):
            ser.break_condition = False
            print("  %2d/%d  KLID   -> TX ma byt ZAPORNY (-5 az -12 V)"
                  % (i + 1, args.cycles), flush=True)
            time.sleep(args.period)
            ser.break_condition = True
            print("  %2d/%d  BREAK  -> TX ma byt KLADNY (+5 az +12 V)"
                  % (i + 1, args.cycles), flush=True)
            time.sleep(args.period)
    except KeyboardInterrupt:
        print("\nkonec")
    finally:
        try:
            ser.break_condition = False
        finally:
            ser.close()


if __name__ == "__main__":
    main()
