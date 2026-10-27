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

### 4505 is tracker 1 only; the sum is the array -- settled 2026-10-27

`4563`/`4564` are the second tracker. `4563` was never in doubt: it moves
independently of `4504` and PI30 exposes nothing like it. The *power* registers
took a high-power measurement to settle, because at low throughput the unit's
own overhead is larger than the quantity being tested.

That measurement, 2026-10-27 09:24, grid off so nothing enters from outside and
the battery current taken from the six BMS shunts rather than from the inverter:

```
battery   113.9 A x 52.66 V = 5998 W   (BMS, six independent shunts)
load                           541 W   (outputPowerActive)
                             -------
provably leaving the array    6539 W

4505 alone                    3702 W   -> impossible, short by 2837 W
4505 + 4564                   7206 W   -> 667 W of loss, 9.3 %
```

9.3 % across MPPT conversion, the 439 V bus -> 52.7 V charger and the unit's own
idle is what this class of hybrid loses. So **`mppt1Power + mppt2Power` is the
array total**, and `solarPowerTotal` now carries it (fresh reads only, see
`MPPT_STALE_S`) in preference to the energy-balance reconstruction.

**InfluxDB keeps the columns it already had.** The array total changed meaning
rather than gaining a neighbour, and in that series tracker 2 is simply
`solarPowerTotal - solarPowerMeasured`. The per-tracker registers are published
to Redis and MQTT for the live display only; `DERIVED_FIELDS` leaves them out of
the per-minute `invertor` measurement and `writePerSecond` strips them from
`invertor_actual`.

PI30 sees tracker 1 and nothing else, confirmed the same morning at every
10-minute bucket: `pvChargingPower` tracked `mppt1Power` to within a few watts
(639/636, 647/650, 529/525, 3316/3316) while `mppt2Power` ran its own curve.

Warning: under about 1.5 kW the sum reads a few hundred watts above anything the
balance can account for -- 2026-10-27 07:20: 888 W claimed against 288 W of
measurable flow, and the gap stays near 550 W across the whole morning instead
of scaling with power. It is not a zero offset: at night both registers read ~0.
It is not a real loss either, since the overnight balance puts the unit's fixed
overhead at 248 W. Suspect the load reading rather than the registers --
`outputPowerActive` reported 277-333 W through a morning whose overnight
standing base was 533 W. Day totals are dominated by the high-power hours, so no
correction factor is applied; one would only hide whichever instrument is wrong.

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
