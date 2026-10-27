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

### Why the balance method had to understate string 2

The reconstruction could only ever see PV that arrived somewhere measurable, so
everything the system loses on the way was silently charged to the one quantity
it did not measure. Tracker 1 is read directly, so the whole shortfall landed on
tracker 2. Measured against the registers on 2026-10-27, per 20-minute bucket:

| time | string 1 | string 2 measured | string 2 from balance | error |
|------|---------:|------------------:|----------------------:|------:|
| 07:00 | 437 W | 308 W | 7 W | -301 W |
| 07:20 | 535 W | 381 W | **0 W** | -381 W |
| 07:40 | 640 W | 478 W | **2 W** | -476 W |
| 08:20 | 1309 W | 1103 W | 710 W | -393 W |
| 09:00 | 3457 W | 3203 W | 2746 W | -457 W |
| 09:20 | 3664 W | 3398 W | 2938 W | -460 W |

The error is roughly **constant at 300-480 W**, not proportional — the signature
of a loss term being dumped on a derived quantity rather than of a bad model.
Through the whole of the early morning the balance reported string 2 as zero
while it was making 300-480 W. Read the registers; measure the losses
separately.

### The losses, measured

Over 111 two-minute buckets of 2026-10-27, grid off, battery from the shunts:

```
useful (load + battery) = 0.933 x PV_gross - 321 W      R2 = 0.95
```

In the steady high-power stretch (09:00-09:20, PV 6.4-6.9 kW) the loss is a very
stable **570-605 W, i.e. 8.4-8.8 %** — ordinary for MPPT + a 439 V bus -> 52.7 V
charger + idle. The awkward part is that the loss stays near 600 W all the way
down to 800 W of PV, where it is 60 % of the reading.

Instruments cleared, so this is not a measurement artefact on the consuming side:
at 07:20 the inverter's own `batteryCurrent` read 0.3 A against the six shunts'
+0.2 A, so both agree the battery took nothing. The load reading is low
(`outputPowerActive` 312 W at 07:30, apparent 504 VA, pf 0.62) but even crediting
the full apparent power does not account for 600 W.

### Settled at dusk, 2026-10-27: no register offset

The loss is proportional to throughput, not a constant daylight overhead, and
the registers carry no positive offset. Two things from the same evening say so.

**The decay is smooth.** Through sunset `solarPowerTotal` walked down
388 → 302 → 206 → 123 → 53 → 20 → 10 → 2 → 0 W as the array voltage fell
290 → 90 → 0 V. An offset would have floored the reading near 600 W and then
dropped it in one step; instead it resolves watts at the bottom of its range.

**With the trackers off the overhead collapses.** 20 ten-minute buckets,
16:40-20:05 UTC, grid breaker open so the battery is the only source and its
power comes from the six shunts:

```
overhead = 15.6 % x load + (-3 W)        R2 = 0.41
mean: load 859 W, overhead 131 W (15.2 %), battery -> AC efficiency 86.8 %
```

So the ~600 W seen at 6.5 kW of PV is the 8-9 % conversion loss of that
throughput, and what remains when the array is dark is ~130 W of DC->AC loss on
a ~860 W load. The fixed term is small: the fit's intercept is zero within the
noise, and the load never dropped below 585 W that evening, so anything under
about 50 W of true idle is still unresolved. A window at 03:00-05:00, where the
house sits near 400 W, would pin it down.

Worth knowing for the energy budget: at ~900 W overnight this is ~1.8 kWh per
14-hour night taken from the bank purely to invert, about 9 % of the night.

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
