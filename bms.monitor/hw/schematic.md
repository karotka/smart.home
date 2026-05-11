# Wiring diagram

Single module, one BMS. The whole thing rides on the pack negative, so
the BMS UART can share GND with the D1 Mini without isolation.

```
       PACK+  ────[PTC 100 mA]────┐
                                  │
                                  ├──► Buck IN+
       PACK-  ───────────────────┐│
                                 │└──► Buck IN-
                                 │
            (shared ground for the rest of the module)

   Buck OUT+ ── 5.00 V ────────► D1 Mini  5V pin
   Buck OUT- ── GND ───────────► D1 Mini  GND pin


   JK BMS GPS port (JST-XH 4-pin)
   ┌──────────────────────┐
   │ 1  VCC (5 V from BMS)│   ─── leave unconnected
   │ 2  TX  (BMS → ext)   │   ─── D1 Mini  D7 / GPIO13  (RX)
   │ 3  RX  (ext → BMS)   │   ─── D1 Mini  D8 / GPIO15  (TX)
   │ 4  GND               │   ─── module GND (same as Buck OUT-)
   └──────────────────────┘
```

## Pin choices on the D1 Mini

The ESP8266's hardware UART (GPIO1/3) is tied to the USB serial bridge
used for programming + the boot console. Don't put the BMS on it —
flashing becomes a chore and the BMS will see boot-time chatter.

Use `SoftwareSerial` on GPIO13/15 instead:

| D1 pin | GPIO | Role     |
|--------|------|----------|
| D7     | 13   | BMS TX → D1 RX |
| D8     | 15   | D1 TX → BMS RX |

D8/GPIO15 has a pull-down on the D1 board — fine as a UART TX.

If you ever need to query the BMS (instead of just passively listening
to what it broadcasts every ~1 s), the RX-into-BMS line is what you'd
use. Listening-only is the default and safer mode; you can leave the
RX line on the BMS side disconnected for the first build.


## Voltage levels & isolation

- BMS UART is 3.3 V logic, ESP8266 GPIOs are 3.3 V → direct connection,
  no level shifter
- All three (pack, BMS, D1) share ground, so the UART works as-is
- Inter-module isolation is done by WiFi (each module talks to the
  server independently, the packs never see each other through any
  signal path)

## Power budget on the pack

| State           | Draw at 5 V | Pack draw at 50 V (avg) |
|-----------------|------------:|-------------------------:|
| Boot / WiFi associating | ~250 mA | ~30 mA peak |
| Idle, WiFi connected   | ~80 mA  | ~10 mA |
| TX burst (every 30 s)  | ~250 mA | brief |

≈ 0.5 W average per module → ~0.24 Ah / 24 h pulled from the pack.
For a 14s30p pack with hundreds of Ah, that's 0.1 % SoC per day.
Negligible.

## Why a PTC fuse, not a glass fuse

If the D1 or the buck shorts, a glass fuse blows and the module is
dead until someone climbs into the cabinet to swap it. A 100 mA-hold
PTC just folds back, the module goes dark, and as soon as the fault
is cleared it recovers on its own — much better for a system that
runs unattended.
