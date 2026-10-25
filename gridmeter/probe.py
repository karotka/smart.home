#!/usr/bin/env python3
"""Find a KLEFR 6914 / Inepro PRO1-Mod on an RS485 line and read it.

The meter is a rebadged Inepro PRO1-Mod (same factory in Nieuw-Vennep, the
address is on the side of the case). Two things make it awkward to talk to,
and between them they account for most failed attempts:

  * it defaults to EVEN parity — 9600 8E1, not the 8N1 nearly every tool
    and tutorial starts with. On 8N1 it simply never answers.
  * Inepro document register addresses in hex, so 0x6000 gets typed into
    clients as 24576, 6000, or 0x6000 depending on what the reader assumed,
    and two of those three are wrong.

Rather than argue with the documentation, sweep: every baud and parity the
meter supports, every address in range, then dump the registers around the
documented ones in both word orders and let the values say which is right.
A float32 that reads as a plausible mains voltage is the answer; one that
reads 3.7e-19 is not.

    python3 probe.py --port /dev/ttyUSB0            # find it
    python3 probe.py --port /dev/ttyUSB0 --dump     # read it once found

Wiring: A -> terminal 23, B -> terminal 24. For a bench test put 120 ohm
across 23/24 at the meter — without the termination a long stub on a cheap
dongle gives intermittent CRC errors that look exactly like "wrong settings".
"""

import argparse
import struct
import sys
import time

import serial

BAUDS    = (9600, 4800, 2400, 1200)
PARITIES = (("E", serial.PARITY_EVEN),
            ("N", serial.PARITY_NONE),
            ("O", serial.PARITY_ODD))

# Inepro PRO1 map, as documented in hex. Names are the meter's own.
REGISTERS = (
    (0x5000, "napeti",            "V"),
    (0x500C, "proud",             "A"),
    (0x5012, "cinny vykon",       "kW"),
    (0x5018, "jalovy vykon",      "kvar"),
    (0x502A, "ucinnik",           ""),
    (0x5034, "frekvence",         "Hz"),
    (0x6000, "celkova energie",   "kWh"),
    (0x600C, "energie odber",     "kWh"),
    (0x6018, "energie dodavka",   "kWh"),
)


def crc16(data: bytes) -> bytes:
    """CRC-16/MODBUS. Not the XMODEM one the inverter link uses."""
    crc = 0xFFFF
    for ch in data:
        crc ^= ch
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes((crc & 0xFF, crc >> 8))


def request(port, addr, fc, reg, count, timeout=0.4):
    """One Modbus RTU read. Returns the payload bytes, or None."""
    frame = struct.pack(">BBHH", addr, fc, reg, count)
    port.reset_input_buffer()
    port.write(frame + crc16(frame))
    port.flush()
    want = 5 + 2 * count          # addr fc len data crc
    deadline = time.time() + timeout
    buf = b""
    while len(buf) < want and time.time() < deadline:
        chunk = port.read(want - len(buf))
        if not chunk:
            break
        buf += chunk
    if len(buf) < 5 or buf[0] != addr:
        return None
    if buf[1] & 0x80:             # exception: the meter IS there and talking
        return b""
    if len(buf) < want or crc16(buf[:-2]) != buf[-2:]:
        return None
    return buf[3:-2]


def openPort(dev, baud, parity):
    return serial.Serial(dev, baudrate=baud, bytesize=8, parity=parity,
                         stopbits=1, timeout=0.3)


def scan(dev, addresses):
    """Sweep baud x parity x address until something answers with a good CRC."""
    for baud in BAUDS:
        for pname, parity in PARITIES:
            try:
                port = openPort(dev, baud, parity)
            except serial.SerialException as e:
                print("nelze otevrit %s: %s" % (dev, e))
                return None
            with port:
                for addr in addresses:
                    for fc in (3, 4):
                        r = request(port, addr, fc, 0x5000, 2)
                        if r is not None:
                            print("NALEZENO  %d baud  8%s1  adresa %d  FC%02d"
                                  % (baud, pname, addr, fc))
                            return baud, pname, parity, addr, fc
            print("  %4d baud 8%s1 — ticho" % (baud, pname))
    return None


def asFloat(raw, swapped):
    if len(raw) != 4:
        return None
    if swapped:
        raw = raw[2:] + raw[:2]
    try:
        return struct.unpack(">f", raw)[0]
    except struct.error:
        return None


def dump(dev, baud, parity, addr, fc):
    with openPort(dev, baud, parity) as port:
        print("\n%-20s %14s %14s" % ("registr", "float", "float (swap)"))
        for reg, name, unit in REGISTERS:
            raw = request(port, addr, fc, reg, 2)
            if not raw:
                print("%-20s %14s" % ("0x%04X %s" % (reg, name), "—"))
                continue
            a, b = asFloat(raw, False), asFloat(raw, True)
            print("%-20s %14s %14s  %s"
                  % ("0x%04X %s" % (reg, name),
                     "%.3f" % a if a is not None else "—",
                     "%.3f" % b if b is not None else "—", unit))
        print("\nSpravne je ten sloupec, kde napeti vyjde kolem 230 "
              "a frekvence kolem 50.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="napr. /dev/ttyUSB0")
    ap.add_argument("--addr", type=int, default=0,
                    help="zkusit jen tuto adresu (0 = projet 1..16)")
    ap.add_argument("--dump", action="store_true",
                    help="po nalezeni rovnou vypsat registry")
    args = ap.parse_args()

    addresses = [args.addr] if args.addr else list(range(1, 17))
    found = scan(args.port, addresses)
    if not found:
        print("\nNic neodpovedelo. Projdi v tomhle poradi:")
        print("  1. A a B prohozene — nejcastejsi pricina a nic se tim nerozbije")
        print("  2. 120 ohm pres svorky 23/24 primo na meraku")
        print("  3. ma merak napajeni? bez 230 V na svorkach 1/4 nekomunikuje")
        print("  4. adresa mimo 1..16 — spust s --addr <n>")
        return 1
    if args.dump:
        dump(args.port, found[0], found[2], found[3], found[4])
    return 0


if __name__ == "__main__":
    sys.exit(main())
