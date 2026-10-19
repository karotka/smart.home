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
optimiser wholesale. **This is in fact the case here** — see the tariff below:
two-rate, but 20 h of NT a day and a 25 % spread, which is close enough to flat
that arbitrage is not where the money is.

### The tariff (owner, 2026-10-14) — answered

**Two-rate, D57d on the contract** (the price list quotes D35d; VT, NT and the
3×25 A breaker charge are identical in both, so only the NT window differs —
**D57d gives 20 h of NT per day**, D35d 16 h).

| | Kč/kWh incl. VAT | of which supply | distribution |
|---|---|---|---|
| **VT** | **4.44** | 3.290 | 0.913 |
| **NT** | **3.55** | 3.180 | 0.141 |

Both include supply, distribution, electricity tax (0.034) and system services
(0.199). POZE works out at 0. Fixed charges **850.47 Kč/month** (supply 163.35,
breaker 3×25 A 671.55, non-network infrastructure 15.57) — a sunk cost that no
control decision changes, so it belongs in payback maths and nowhere else.

What this means for the objective:

- **The spread is only 0.89 Kč/kWh (25 %), and NT covers 20 hours a day.** This
  is nearly a flat tariff in practice: there is very little price arbitrage to
  chase, and building a spot-price optimiser for it would be wasted effort.
- So the objective really does collapse to the two things in §2: **don't waste
  solar, and keep enough charge for the night.** Every kWh of curtailed solar
  used is worth 3.55–4.44 Kč; every kWh imported costs the same. That single
  number is the whole price model.
- The 4 h of VT per day is worth knowing but is a second-order correction —
  worth deferring a discretionary load out of, not worth optimising around.

**What the grid actually costs here (owner, 2026-10-15).** Real import is
**4–5 MWh/year** against a total annual bill of about **26 000 Kč**, which the
price list reproduces almost exactly (4.5 MWh × 3.55 + 12 × 850.47 = 26 181).
So the *average* kWh costs **~5.8 Kč**. Keep the two numbers apart, because
they answer different questions:

- **3.55 Kč is the marginal price** and the one the optimiser wants. Using one
  kWh less saves exactly that; the fixed 10 206 Kč/year does not move. It is
  therefore also what a kWh of rescued curtailment is worth — on 10-05 and
  10-06, 24 and 23 kWh were thrown away, about 85 Kč a day.
- **10 206 Kč/year is the cost of having the connection at all**, and only a
  smaller breaker or disconnection touches it. Nothing the controller does can.

⚠ **Do not extrapolate October.** An attempt to read annual import off a
mid-October fortnight gave ~300 kWh/year and the conclusion that the monthly
advance was set far too high. It is not — at 4–5 MWh the advance is about
right. October runs 40–50 kWh/day of solar; December does not. Any figure in
this file derived from autumn data needs a winter to confirm it, the heat-loss
coefficient included.

### Comfort band (owner, 2026-10-14) — answered in principle

Take the band from the **setpoints already in use**, which the state recorder
now logs per room (`target_<room>` in measurement `control_state`). Measured
2026-10-14: obyvak 24.75, koupelna 25.75, kacka 23.0, kluci 22.75, vchod 21.75,
loznice 21.5 (**deliberately off**), garaz 26.0, petr 21.25.

Two caveats that shape how this can be used:

- **The garage is inside the envelope**, between loznice and kluci, with
  uninsulated doors, and its 26 °C is a surplus dump rather than a comfort
  requirement. It is the one "setpoint" the optimiser may freely sacrifice —
  and the one place it may freely dump.
- **kluci is south-facing** and runs above setpoint on sunny days from solar
  gain alone; loznice is switched off on purpose. Neither calls for heat, so
  neither constrains the schedule.

**Lower edge: 2 K below setpoint** (owner, 2026-10-15) — "no more than two
degrees". So the band is `[target − 2, target]` per room, with the garage
exempt: its 26 °C is a dump target, not a comfort requirement, and may be
sacrificed freely.

That closes both of the inputs this note was blocked on. What the 2 K actually
buys is still unmeasured though, and it is one number: the **cooldown time
constant** of the house. With it, 2 K converts into hours of heating the
optimiser may defer — the house as a thermal battery, with a capacity in kWh
rather than in degrees. Without it, the band is a constraint that cannot be
spent.

It is measurable from data already being collected: find a stretch with the
heat pump off, fit the decay of indoor temperature against outdoor, and
combine with UA. The state recorder now logs per-room manifold hours and
setpoints, so those stretches can be found rather than stumbled on. Do this
once there is a winter stretch — an autumn one would inherit the same seasonal
bias as everything else here.

⚠ **The garage sensor measures the inverter corner, not the garage.** Flashed
2026-10-17 (id 10040010, 192.168.0.18), it sits beside the inverter Pi and is
powered from its USB, so it shares that Pi's fate on a power cut. More
importantly for the heat-loss fit: the inverters dissipate real heat and they
do it hardest on sunny days — which is exactly when surplus is dumped into the
garage floor. Two effects the fit is meant to separate will therefore arrive
correlated, and the reading will sit above true garage air temperature by an
amount that grows with throughput. Inverter power is logged, so the
contamination can be regressed out; just don't read the raw series as garage
temperature.

Side finding, and a corrected one. The board reports −82 to −95 dBm there,
which was first read as evidence that the corner has bad wifi and therefore
explains the repeated dropouts on .225. **That inference was wrong.** Measured
in the same corner on 2026-10-17:

    Pi second   −65 dBm
    Pi first    −69 dBm
    ESP garaz   −95 dBm

A 26–30 dB gap, i.e. about a thousandfold in received power. The corner is
fine for a Pi; what the sensor measured is its own PCB-trace antenna against
the Pi's real one. So the 528 network failures logged by the BMS daemon on
.225 are *not* established as a signal problem and still want a cause. The
ethernet cable moved to .225 on 2026-10-17 regardless, since that Pi carries
both the BMS daemon and invertor-first; whether the failure count stops
growing is now the test of what they actually were.

What the gap does establish is that **the garage sensor is the device at
risk**: −95 dBm sits at the edge of ESP8266 sensitivity (−91 to −98 depending
on rate), so expect missed samples there, and treat a gap in that series as a
radio problem rather than a sensor fault.

### Zone priority and the garage rule (owner, 2026-10-19)

Stated plainly by the owner, and these are rules rather than thresholds:

1. **The garage heats only from surplus, and only once the buffer tank is
   satisfied.** It is a dump, third in line, and must never draw from the grid
   or the battery. The night of 2026-10-18/19 is what prompted this: with the
   grid on and the garage setpoint left at 19.75 °C against a room at ~19.2, it
   ran 8.3 h and took 4.17 kWh — 30 % of all heat that night, bought at
   3.55 Kč/kWh and sent through uninsulated doors.
2. **The bathroom outranks the garage.**

**The tank is a heating buffer, not DHW** (owner, 2026-10-19) — corrected from
an earlier reading of this file. It sits behind the heat pump to stop the
compressor short-cycling. The floor circuit runs at about 37 °C and a mixing
valve on the tank outlet blends in return water to bring it *down* when needed;
it can only cool, never heat. DHW is separate — thermal-solar plus an
occasional electric spiral — and not this controller's problem.

Two different numbers, and they are easy to conflate:

- **≥38 °C is the floor's working minimum**, one degree over what the circuit
  wants. Below this the floor simply runs cool.
- **≥55 °C is the bar for the garage**, because **the tank is the first place
  surplus should go**. It is the cheapest store there is — small, and the heat
  in it is directly useful. Only once it is genuinely charged does putting
  energy into a garage slab behind uninsulated doors make sense.

So the rule is `garage ⟺ boost active ∧ tank ≥ 55 °C`.

55 is well placed, measured over 96 h: during boost the tank sits at a median
of 56.0 °C and is above 55 three-quarters of the time; without boost the median
is 39.0 and it clears 55 only 5 % of the time. Daily maxima track the weather
exactly — 61.0, 58.0, 58.0 on the sunny 15th–17th, then 45.0 and 42.0 on the
overcast 18th–19th. The threshold separates genuine abundance from everything
else without needing a second condition to help it.

It works despite the boost targeting only 50 °C, because the pump overshoots:
on 2026-10-15 the target was 50 and the outlet went to 60. Worth knowing that
the margin depends on that overshoot rather than on the setpoint.

**The PG1[4] number is not the outlet temperature** (owner, 2026-10-19), and
reading it as one leads straight to a wrong conclusion. A setting of 32 gives
an outlet of about 37 °C — which is exactly what the floor wants. So the quiet
modes are *not* running the floor cold, as an earlier version of this note
claimed; they are running it correctly.

It also disposes of an apparent anomaly recorded here: that on the night of
2026-10-18/19 the outlet held 36-39 °C while the target read 32. That is simply
what 32 produces. Nothing was overriding the scheduler and nothing needs
explaining.

The same offset shows at the other end — the boost sets 50 and the outlet
reached 60 on 2026-10-15, which is why the tank clears 55.

**And the offset is a setting, not a quirk** (owner, 2026-10-19, from the
pump's Temperature Setting screen). PG1[4] is the target for the *return*
water, and a second parameter, "Return water & target DHW water temp
difference", is set to **5 °C** — so the pump runs the flow 5 °C above the
return target: 32 → 37, 50 → 55-plus. A third parameter on the same screen,
"Return difference for heating & cooling function" = **2 °C**, is the
hysteresis: the compressor restarts once the return has fallen 2 °C below
target.

That makes the floor temperature adjustable from two directions, which is
worth knowing before adding control logic:

- raise PG1[4] and both return and flow move together (what the scheduler
  does today);
- raise the 5 °C difference and the flow rises while the return target stays
  — a hotter floor at the same stored temperature, i.e. more heat per pass
  rather than a hotter buffer.

The range on the difference is 2-18 °C, so there is a lot of room there. The
scheduler only ever touches PG1[4]; the other two are set by hand in the app
and nothing in this repo writes them.

### The flow temperature at the manifold — a signal we already had

Everything above infers the floor's water temperature from the pump's end of
the circuit. There is a direct measurement, and it was running the whole time
(owner, 2026-10-19: "teplota topné vody před rozdělovačem se taky někam
posílá").

The manifold board carries a 100 kΩ NTC (`manifold.switch/thermistor.h`) and
pings the web app every 20 s with the reading attached:
`GET /ping?t=<millis>&te=<°C>`. The handler in `server_fastapi.py` parks it in
Redis as **`heating_watter`** — two t's, a typo old enough to be load-bearing;
`server.py` spells it the same way and nothing else reads it.

Two things about that chain are worth writing down:

- **The flashed firmware is ahead of this repo.** The committed
  `manigold.switch.ino` includes `thermistor.h` but never calls it and never
  sends `te`; the live board does both. Read the device, not the source.
- **It used to be archived and silently stopped.** An InfluxDB measurement
  `heating_water` (field `temperature`, one point per 20 s) runs from at least
  2025-09 to **2026-06-13 15:43 UTC** and then nothing. Whatever wrote it is
  not in this repo and not on .224 — most likely a loose script on the Pi4,
  which is off. Four months of flow temperature were lost without anyone
  noticing, which is the argument for recording it somewhere maintained.

Revived 2026-10-19 as a field of `control_state`:
`state_recorder.py` now samples `heating_watter` into **`water_manifold_c`**
every 60 s, alongside the manifold port states and the scheduler mode. That
puts flow temperature, which ports were open, and why, on the same timeline —
the join that any per-room energy signature needs.

**It is only a flow temperature while the pump runs** (owner, 2026-10-19). The
thermistor sits on the pipe under the insulation, so with the pump stopped it
reads the water standing in that pipe, which cools very slowly — a thermal
memory of the last run, not a measurement of anything current. The 30 °C
showing as this was written is exactly that: the pump had been off since
17:51 UTC because no room was calling for heat.

The decay is slow enough to be worth a number. On 2026-01-15 circulation
stopped around 08:00 at 31 °C and the pipe was still at 23.8 °C six hours
later, a time constant of roughly 2-5 h depending on where ambient sits. So
a stale reading stays plausible-looking for most of a day, and nothing in the
value itself says whether it is live.

**The NTC itself is accurate.** First live comparison, 2026-10-19 20:23 with
the bathroom loop circulating: the manifold thermistor read 33.4 °C while the
heat pump's own outlet sensor read 33 (`waterOutletTemperature`, db `hp`).
Agreement to 0.4 °C, so a pipe-surface sensor under insulation needs no
correction for being outside the water — worth knowing before anyone proposes
one.

The same reading shows what the signal is for. Tank 37 °C, flow 33, return
31: the floor gets 33 and gives back 2 °C, on a night target of 32 with the
compressor stopped (0 Hz, 40 W standby, 6 °C outside) because the tank is
already at target — 32 + the 5 °C difference. So "32 gives 37" describes the
tank, and what actually reaches the floor on the night setting is 33. The
morning-slot design has to start from that number, not from the tank.

Starting the pump is unmistakable in the data: 27.1 °C stagnant at 20:04,
then 27.8 / 29.5 / 31.3 / 32.2 over the next three minutes once the bathroom
port opened. Nothing else in the system moves a pipe 4.5 °C in three minutes.

One nuance on the stale case. A *short* closure does not decay — during the
3-minute gaps at 20:09 and 20:16 the reading rose (32.56 → 32.70,
32.97 → 33.28), because with no draw the pipe equilibrates upward toward the
37 °C tank instead of downward toward ambient. Long off decays, short off
climbs; neither is a flow temperature, so the rule below is unchanged, but
don't read a rising trace as proof that water is moving.

Reading it correctly therefore means joining on `heating_state`, which the
recorder stores in the same measurement — the relay is the circulation pump,
so `heating_state = 1` is the only window where the field means what its name
says. For settled values, take samples where the *previous* sample was also 1,
since the first minute of a run is the pipe warming through. Everything else
is residual and should be dropped, not averaged in.

Why it matters for the control problem specifically: the garage gate and the
bathroom morning slot are both written against the *tank* (DPS 108), which is
upstream of the mixing valve. `water_manifold_c` is what the floor actually
receives, downstream of the blend. Once there is a heating season of it, the
gate can be stated in terms of the thing it is really about.

⚠ **Never probe the manifold with curl.** The firmware takes characters 5-13
of the request line as the relay word — `'0'` closes a port, any other
character opens it. So `GET /temperature` parses as `"temperatu"`, nine
non-zero characters, and **opens all nine valves**. Done accidentally while
investigating this (2026-10-19) and closed again with `/000000000`; the
heating relay was off throughout, so nothing circulated. `checker.py` writes
the manifold only on change, so it would not have corrected itself. To read
the temperature, read Redis `heating_watter` or `control_state`, never the
device.

Verified that the target actually reaches the pump, since it would be easy to
assume otherwise: PG1[4] read live is the value the scheduler wrote, and on
2026-10-15 a boost to 50 °C took the outlet from 32.7 °C to 44.5 within fifteen
minutes and on upward. The register works.

### What the bathroom measurement says about *when* to heat

Measured over 84 h from the state recorder (port state) and its sensor:

```
heating (port open)    p75 +0.40 °C/h   p90 +0.80 °C/h
cooling (port closed)  median −0.20 °C/h
port open              40 % of the time
range seen             24.9 – 28.3 °C
```

The owner's instinct to start around 04:00 is right *if* setting back: eight
hours off costs about 1.6 °C and recovering that takes two to four hours.

**But night setback is the wrong lever here.** The saving comes from a lower
average temperature, and the bathroom is perhaps an eighth of the floor area,
so of the house's ~100 W/K it carries maybe 8 W/K. One degree lower for eight
hours saves 64 Wh of heat, ~21 Wh electric at COP 3 — seven haléřů. And part
of what it loses goes into neighbouring rooms, where it is wanted anyway.

The lever that matters is **when**, not how much. At −0.20 °C/h the room holds
heat extremely well: from the 28.3 °C it reached it would take ten hours to
drift to 26. The floor is a store. So the right pattern is to charge it through
the midday surplus and let it coast through evening and night, which trades
3.55 Kč/kWh for nothing — four hundred times the setback saving. On that
pattern the owner's second slot at 18:00 is unnecessary.

Caveat: this measures air, not slab. The floor can stay warm while the air
drifts, so true inertia is better than the figure above, not worse.

**And the air was the wrong variable anyway** (owner, 2026-10-19). Bathroom air
temperature does not matter as long as it stays above 24.5 °C. What matters is
a **warm floor from 05:00**, which he puts at starting the loop around 04:45.

That is a different control problem from everything above, because the two
have completely different time constants: the air has the ten-hour one we
measured, while the floor *surface* follows the flow within minutes. So this is
a schedule with a deadline, not a thermostat — and the 15 minutes of lead he
quotes is about the surface, not the room.

The trap: `night` targets 32 °C. Opening the bathroom port at 04:45 in that
mode puts 32 °C water into a floor in a 24.5 °C room, which reads as neutral,
not warm. **The morning slot needs the pump target at working temperature
(≥38 °C) as well as the port open** — raising one without the other achieves
nothing.

For the optimiser this is a hard constraint with a clock on it: the buffer has
to be at working temperature by 04:45, and the interesting question is whether
it can get there from stored energy rather than off the grid at the worst hour
of the night. That is exactly the kind of thing a horizon is for, and the
reason an instantaneous rule cannot do this part.

### ⚠ Still open

1. What is a battery cycle worth (degradation cost per kWh)?
2. Is there a DHW minimum that must always be held? (DHW is thermal-solar plus
   an occasional electric spiral, not the heat pump — so possibly not a
   constraint on this controller at all.)

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
