# JK BMS GPS-port cable

The JK BD6A24S10P doesn't ship a UART cable in the box — only the BMS
itself and (optionally) a Bluetooth dongle. The "GPS port" is a 4-pin
JST-XH 2.54 mm socket on the side of the BMS PCB; everything we need
is that connector plus four wires.

Two options:

## A. Sacrifice the Bluetooth dongle cable

If you have a JK Bluetooth dongle and don't plan to keep using it,
cut the cable a few cm from the JST plug end. You now have:

  - the correct 4-pin JST-XH plug already wired and tested
  - four colour-coded conductors

Solder them straight to the D1 Mini per `schematic.md`. Done.

## B. Build a fresh one

You need:

  - JST-XH 2.54 mm 4-pin **plug** (matches the BMS socket)
  - 4× crimp terminals for it
  - ~10 cm of 4-conductor wire (or four 28-AWG hookup wires)

Layout when the plug is facing you with the locking tab up, pin 1 on
the left (this is the standard JST-XH orientation):

```
   ┌───────────────────┐
   │ ┌──┐ ┌──┐ ┌──┐ ┌──┐│        Pin 1 ── VCC  (5 V from BMS — leave unconnected)
   │ │  │ │  │ │  │ │  ││        Pin 2 ── TX   (BMS → D1)
   │ │  │ │  │ │  │ │  ││        Pin 3 ── RX   (D1 → BMS; optional)
   │ └──┘ └──┘ └──┘ └──┘│        Pin 4 ── GND
   │   1    2    3    4 │
   └─────────tab────────┘
                ↑
           locking ear
```

## Verify before you trust the wiring

Before plugging the cable into the BMS, **measure with a multimeter**:

  1. Plug the cable into the BMS socket with the BMS powered on
  2. Black probe on pin 4 (your GND), red probe on each pin in turn
  3. You should see roughly:
     - pin 1: ~5 V (constant)
     - pin 2: 3.3 V quiescent, briefly dipping every ~1 s (this is the
       UART idle level + the start of each broadcast frame)
     - pin 3: ~0 V (idle UART input on the BMS side)
     - pin 4: 0 V

If pin 1 is 3.3 V instead of 5 V you have a different revision of the
JK firmware — still fine, just don't use that pin to power anything.

If you see any voltage > 5 V on pins 2 / 3, **stop**: it is not a
JK GPS port. Cross-reference your BMS silkscreen with the JK manual
for your model and re-check the connector you grabbed.

## Strain relief

Whatever you build, secure the cable mechanically to the enclosure
(zip-tie through a slot, or a hot-glue dab where it enters). The JST
contacts will fatigue if the plug is the only thing holding the cable
to the BMS.
