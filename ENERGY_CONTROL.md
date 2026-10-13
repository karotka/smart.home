# Automatic energy control — design note

**Status: DESIGN NOTE. Nothing here is implemented yet.** What runs today is the
rule list in `web/checker.py` (`checkHeatingSchedule` + `checkSolarBoost`),
described under "Where we are now". This file exists so the discussion that led
here isn't lost, and so the next attempt starts from the objective rather than
from more thresholds.

Started 2026-10-13.

---

## 1. The problem with what we have

The heat-pump control is a list of thresholds:

```
night (21:00-07:00)                          -> 32 °C + mute
day,  battery not charging                   -> 32 °C + mute
day,  SoC >= 80 % AND charge >= 5 A          -> 37 °C + smart
      AND discharge <= 2 A
surplus: SoC >= 85 % AND charge >= 15 A      -> 50 °C (solar boost)
```

Every one of those numbers is a guess. The real problem isn't that they're the
wrong guesses — it's that **there is nothing to tune them against**. Ask "should
the threshold be 80 % or 70 % SoC?" and there's no way to answer, because no
quantity has been defined that one choice makes better than the other.

That shows up as rules quietly contradicting each other. Two real examples:

- **2026-10-13, ~12:30.** Solar was making 9.8 kW and the battery was charging at
  147 A against a 150 A cap (the slave inverter pinned at exactly its 70 A limit).
  Everything above that cap was being curtailed and thrown away. But SoC was only
  52-65 %, so the "charging has priority" rule kept the heat pump off — refusing
  to use energy that could not have gone into the battery under any circumstance.
- **2026-10-12 night.** Grid physically disconnected, heat pump on, no sun the
  previous day. The battery went to 48.3 V / 3.44 V per cell by 06:50 and was
  ~2 h from the inverters' 45.5 V shutdown. No rule saw it coming, because every
  rule looks only at the present instant.

The first case wastes free energy. The second nearly blacked out the house. Both
are the same defect: **the rules describe states, not consequences.**

---

## 2. What to optimise (the missing piece)

The objective, stated plainly:

> **Minimise money spent importing from the grid over a horizon (1-2 days),
> subject to comfort and battery-health constraints.**

Constraints:
- comfort — house temperature inside an acceptable band, DHW above a minimum
- battery health — don't deep-discharge, don't sit at high SoC for long
- equipment limits — charge-current caps, inverter ratings

If the tariff is flat, the whole price-arbitrage machinery is unnecessary and the
objective collapses to two things: **don't waste solar**, and **keep enough
charge for the night**. That is a much smaller problem than the one most
published work solves, and worth exploiting rather than copying a spot-price
optimiser wholesale.

### ⚠ Open questions — needed before any of this can be written

1. **Electricity tariff.** Flat / two-rate (VT-NT) / spot? This decides whether
   there is anything to arbitrage at all.
2. **Comfort band.** At what indoor temperature is it still fine, and at what
   point is it not? This is the exchange rate that converts heat into money —
   without it "is running the heat pump worth it?" has no answer.
3. Secondary: what is a battery cycle worth (degradation cost per kWh), and is
   there a DHW minimum that must always be held?

---

## 3. The idea that replaces the rule list

**One number: the marginal cost of the next kWh, right now.**

| where the next kWh comes from | marginal cost |
|---|---|
| curtailed solar (charge cap reached, or battery full) | **0** — use it or lose it |
| solar that would otherwise charge the battery | value of that kWh tonight ≈ grid price × round-trip efficiency − degradation |
| battery discharge | same, but spent now instead of later |
| grid import | the tariff price |

Every load decision then becomes one sentence:

> **Run the load if the value of what it produces ≥ the marginal cost of the
> energy it consumes.**

This is not another rule to add — it *subsumes* the existing ones. The
"charge-capped solar is free" case that triggered this whole discussion is simply
the first row of that table; it doesn't need special handling.

What it buys: instead of tuning `SoC>=80 && PV>=1500 && charge>=5 && discharge<=2
&& hour in 7..21`, there is a single quantity to reason about, and the tuning
knob becomes a question a human can actually answer ("how much is hot water worth
to me?") rather than one nobody can ("is 80 % the right SoC?").

---

## 4. Why marginal cost alone still isn't enough

Computed from the present instant only, it is greedy. The failure mode is
concrete: dump surplus into 50 °C water at 10:00, cloud bank arrives at noon,
and there is nothing left for the night. That is the 2026-10-12 incident.

No instantaneous threshold can fix this, because the right answer depends on the
future. It needs:

- **PV forecast** — free sources: forecast.solar, Open-Meteo
- **load forecast** — can start as a simple historical profile
- **a horizon** — "does the evening reserve still fit if I spend this now?"

Treating the house and DHW tank as **thermal storage with a comfort band** (a
second battery, with temperature as its state of charge) is the standard framing
and the one that makes the heat pump schedulable instead of reactive.

---

## 5. Prior art

- **[EMHASS](https://emhass.readthedocs.io/)** ([GitHub](https://github.com/davidusb-geek/emhass))
  — closest match to what's needed here. LP/MILP optimisation, PV and load
  forecasting, deferrable loads, and explicitly models **thermal inertia of
  water heaters and heat pumps as energy storage**. Has an MPC mode and
  multi-battery support. Home-Assistant-oriented, which we don't run — so it's
  either a dependency to adopt or a reference design to copy from.
- **Model Predictive Control** — the standard approach: re-solve a
  receding-horizon optimisation every few minutes over a 24-48 h forecast.
  [Heat pump + thermal storage MPC](https://arxiv.org/pdf/2003.11990),
  [economic MPC for buildings](https://arxiv.org/pdf/1906.00362).
- **[High PV, low battery](https://arxiv.org/pdf/2505.20377)** — notable because
  it is exactly this installation's shape (14.4 kWp against ~10-12 kWh of real
  usable storage), and finds that algorithmic control matters most in that case.
- **evcc**, **Victron Dynamic ESS**, **Predbat** — production implementations of
  the same principle.

---

## 6. Proposed path (smallest useful step first)

1. **Marginal cost signal.** Compute it every tick and drive the existing actions
   (32 / 37 / 50 °C) from it instead of the threshold soup. Contained change
   inside `checker.py`; removes the contradictions and handles the charge-capped
   case for free.
2. **PV forecast** for today and tomorrow. Only with this can "spend now or save
   for tonight" be answered at all.
3. **Comfort band instead of fixed setpoints** — give the heat pump a temperature
   range and let it choose when within it to heat.
4. *Optional, large:* real horizon optimisation — or adopt EMHASS rather than
   writing it.

Steps 1 and 2 are judged to carry most of the benefit for a fraction of the
effort. Step 4 is a project with an uncertain increment on top of them.

---

## 7. Mixed chemistry on one bus — what actually happens

Observed 2026-10-13, the first full day with the LFP paralleled, and it changes
what "how full is the battery" even means.

One bus, two different voltage-vs-SoC curves, so the packs sit at *different*
states of charge at any given bus voltage. At 53.8 V:

```
lfp-1      3.361 V/cell   +38 A      (mid-plateau — still hungry)
battery-4  3.843 V/cell    +1 A
battery-3  3.843 V/cell    +1 A
battery-5  3.844 V/cell    -1 A      ) these three are discharging
battery-1  3.841 V/cell    -2 A      ) INTO the LFP
battery-2  3.847 V/cell    -3 A      )
```

**The LFP's flat plateau clamps the bus.** It absorbs very large amounts of
energy without its own voltage rising (3.363 → 3.361 V over an hour at 40-50 A),
so the bus can't rise either — and the NMC packs, which at that bus voltage are
already at 3.84 V/cell, simply stop charging. They only resume once the LFP
reaches its knee (~3.45 V/cell ≈ 55.2 V bus), which from mid-plateau is another
~3-4 kWh of absorption. On a short winter day that point may never be reached,
leaving the NMC parked around 70 % for days.

Net effect: **the LFP does the cycling, the NMC are a reserve that only
participates at the extremes of the bus voltage.** That is what the original plan
intended ("be gentle on the NMC, take the deep tail from the LFP"), but it
arrives as a side effect of the chemistry rather than as something controlled.

**This is good for the NMC.** They now live in roughly 3.4-3.9 V/cell (~20-80 %
SoC) — no deep discharge, and no sitting at high state of charge, which is the
dominant driver of calendar ageing in Li-ion. For battery-3 (267 cycles, already
degraded) that is worth real lifetime.

The costs: their mid-range capacity is effectively unavailable, and they no
longer reach the top of charge, so **their BMS balancing never runs**.

### Consequences for the optimiser

- **"Battery SoC" is not one number.** Usable energy depends on which chemistry
  is holding the bus and where it sits on its own curve. Any objective function
  needs per-pack state, not a bank average.
- **Trust cell voltage over reported SoC.** The LFP BMS claimed 98 % / 226 Ah of
  230 Ah while its cells were at 3.361 V — mid-plateau, so realistically 60-70 %.
  Its coulomb counter started from a wrong baseline and is offset roughly +30
  points. It will re-calibrate itself the first time the pack actually reaches
  full charge voltage. The same error appeared inverted that morning: 45 %
  reported at 3.026 V/cell, when the voltage said closer to 10 %.
- Charging the NMC to full would require deliberately pushing the bus high,
  which conflicts with keeping them in the longevity window. Probably not worth
  doing except occasionally, to let them balance.

---

## 8. Hardware constraints worth remembering here

- **Charge current is capped at 150 A total** (master 80 A + slave 70 A). The
  slave cannot be raised: in parallel it ACKs an MNCHGC write and ignores it, and
  the master's value doesn't propagate. `MNCHGC 160` to the master is rejected
  outright (NAK), so there is no "total for the pair" to distribute — the limit
  is per unit and additive. Above ~8 kW of PV into the battery, solar *will* be
  curtailed, and that curtailed energy is the cheapest input the system has.
- Output priority is **SUB** on both (utility before battery). Switching to SBU
  is only sensible once storage is large enough not to sag to the mains-switch
  point under load — see CLAUDE.md.
- Real usable storage is roughly **half** the nominal figure on the NMC side, and
  BMS SoC readings are optimistic. For the LFP pack, trust **cell voltage** over
  reported SoC until it has been through a full charge cycle and calibrated.
