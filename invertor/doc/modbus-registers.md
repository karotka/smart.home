# Easun VMII-NXPW5KW9 — Modbus RTU register map

The 10 kW Easun answers **two protocols on the same RS232 line**: the Voltronic
PI30 ASCII commands (`QPIGS`, `QPIRI`, …) and **Modbus RTU, slave 5, 2400 Bd**.
Nothing extra is needed — no RS485, no WiFi dongle. See `CLAUDE.md` for how this
was found and for the dead ends that preceded it.

Two traps:

* **Only function 3** (read holding registers). Function 4 is refused.
* **Register words are little-endian.** `0xB901` is 441 (44.1 V), not 47361.
  Standard Modbus would decode the other way round.

The map runs from **4500 to 4564**. Outside that every register reads `20705`
(0x50E1) — that filler value is how you tell "end of map" from a real reading.
Reads of more than eight registers at a time are often truncated; single reads
always work.

## Measurements

| Reg | Scale | Meaning | Cross-check |
|-----|-------|---------|-------------|
| 4504 | 0.1 V | PV1 voltage | = `QPIGS` PV input voltage |
| 4505 | W | PV power — **see the warning below** | = `QPIGS` PV charging power |
| 4506 | 0.1 V | Battery voltage | = `QPIGS` |
| 4507 | 0.1 A | Battery current | |
| 4510 | 0.1 V | AC output voltage | = `QPIGS` |
| 4511 | 0.01 Hz | Output frequency | |
| 4512 | VA | Output apparent power | = `QPIGS` |
| 4513 | W | Output active power | = `QPIGS` |
| 4517 | 0.1 °C | Temperature | |
| 4553 | bits | Status flags | |
| 4557 | °C | Heat-sink temperature | agrees with `QPIGS` |
| 4563 | 0.1 V | **PV2 voltage** | nowhere in PI30 |
| 4564 | W | **PV2 power** — see the warning | nowhere in PI30 |

### Warning: 4505 and 4564 do not add up to the array total

`4563` is unambiguous and valuable: it is the second tracker's voltage, it moves
independently of `4504`, and PI30 exposes nothing like it. The *power* registers
are a different story.

Measured 2026-10-27 morning, with the grid off so the balance is clean and the
battery current taken from the BMS (six shunts) rather than the inverter:

```
load 306 W + battery 79 W = 385 W actually consumed
4505 alone                 601 W   -> 216 W overhead
4505 + 4564               1036 W   -> 651 W overhead
```

Overnight the same balance gives the inverter's real overhead as **248 W at a
1.5 kW load** (battery 21.42 kWh out by BMS, 18.43 kWh at the output), and the
manual puts no-load consumption at 75 W. 651 W of overhead at a 306 W load is
not physically possible, so **the sum is wrong**. Either 4505 is already the
array total and 4564 is a subset of it, or both registers are inflated by a
constant factor.

Do not publish `mppt1Power + mppt2Power` as the array total until this is
settled against a high-power day, where the overhead is a small fraction of the
reading instead of most of it. The balance reconstruction in `solarPowerTotal`
stays in place meanwhile.

## Settings (read-back)

This block mirrors what the LCD menu shows, which makes it possible to verify a
setting without walking to the inverter. Verified against the `QPIRI` snapshot.

| Reg | Scale | Setting | Value on 2026-10-27 |
|-----|-------|---------|---------------------|
| 4525 | 0.1 V | Rated battery voltage | 48.0 |
| 4526 | V | Rated AC output voltage | 230 |
| 4527 | 0.01 Hz | Rated output frequency | 50.0 |
| 4541 | A | Max solar charging current | 160 |
| 4544 | 0.1 V | **Back to grid** (prog. 12) | 49.0 |
| 4545 | 0.1 V | **Back to battery** (prog. 13) | 51.0 |
| 4546 | 0.1 V | Bulk / absorption | 58.0 |
| 4547 | 0.1 V | Float | 57.9 |
| 4548 | 0.1 V | Low cut-off | 45.5 |
| 4531–4533 | — | Serial number digits (`5535`, cf. `QID`) | |

Reading is safe. **Writing is not attempted**: every setting write costs an
EEPROM cycle, and the September outage series came from exactly that. Settings
changes stay manual and owner-approved, over PI30, as `CLAUDE.md` requires.

## Line sharing

`invertor.py` interleaves one Modbus poll every 30 s between the one-second PI30
cycles, clears the input buffer in a `finally`, swallows its own exceptions and
gives up entirely after 20 consecutive failures. PI30 outranks it: an MPPT read
may never cost a `QPIGS`. Measured 6/6 clean before deployment.
