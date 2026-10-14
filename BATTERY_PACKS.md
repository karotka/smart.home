# Battery pack registry

What each pack in the bank physically *is*. Started 2026-10-14 because the composition
existed only in the owner's head, and without it the measured data gets misread — see
"How to read the numbers" below for the mistake this file exists to prevent.

Every row is tagged with where it came from:

- **[M]** measured from BMS data — reproducible, see "Regenerating the numbers"
- **[O]** stated by the owner
- **[?]** not established yet — needs a physical check

---

## 1. The packs

All five NMC packs are 14S on a shared DC bus, each with its own JK BD6A24S10P BMS.
The LiFePO4 pack joined the same bus 2026-10-12.

| pack | parallel | cell type **[O]** | nominal | notes |
|------|----------|-------------------|---------|-------|
| battery-1 | **44p**14s | Samsung INR18650-30E | 3000 mAh | wrapper blue |
| battery-2 | 40p14s | Samsung INR 18650, **part number [?]** | — | wrapper green; measurement points at a 3000 mAh class cell, see §2 |
| battery-3 | 30p14s | Panasonic NCR18650**PF** *(probable)* | 2900 mAh | assembled from mixed salvage, so not necessarily one type |
| battery-4 | 60p14s | Panasonic, **ex-Tesla**, built as 2×30p | ~3400 mAh | largest pack |
| battery-5 | 30p14s | LG INR18650-**MH1** | 3200 mAh | |
| lfp-1 | 16S | EVE LF230 | 230 Ah | prismatic, not 18650; measured 239.8 Ah = 104 % of nameplate |

Total NMC cells: 14 × (44+40+30+60+30) = **2856**.

Earlier revisions of this file had battery-1 at 40p and called battery-1/2 "LG";
both were wrong (owner, 2026-10-14). The parallel count matters — every per-cell
figure divides by it.

### Still to establish [?]

1. **battery-2 — the Samsung part number.** §2 narrows it to a ~3000 mAh cell
   (30Q or 30E); look for those first.
2. **battery-3 — confirm PF, and what else is in the mix.** Being salvage, a single
   part number may not exist; "mostly X with some Y" is a useful answer.
3. **BMS board serials.** The JK device-info frame (type `0x03`) carries vendor id,
   manufacture date and serial, but `bms_daemon.py` only parses `0x01` (settings) and
   `0x02` (cell info), so we don't capture it. Worth adding if hard identifiers are
   wanted — it would pin each board, though *not* the cells.

### What to look for when a pack is opened

Cell markings are usually laser-etched on the positive end or printed on the wrapper.
Wrapper colour alone is suggestive, not conclusive — LG blue and LG green are common to
several part numbers. If the markings are gone (reclaimed cells often are), the
cross-check below narrows it.

---

## 2. Measured, 2026-10-14

Delivered Ah during the deep night of 2026-10-13 (bus 53 → 48.3 V), which is the widest
clean discharge on record.

| pack | parallel | delivered **[M]** | **per cell [M]** | cycles **[M]** | BMS limit chg/dch **[M]** | per cell |
|------|----------|-----------|--------------|--------|-------------------|----------|
| battery-1 | 44p | 41.6 Ah | **0.95 Ah** | 45 | 50 / 100 A | 1.14 / 2.27 A |
| battery-2 | 40p | 35.1 Ah | **0.88 Ah** | 46 | 50 / 100 A | 1.25 / 2.50 A |
| battery-3 | 30p | 25.2 Ah | **0.84 Ah** | **268** | 30 / 100 A | 1.00 / 3.33 A |
| battery-4 | 60p | 54.4 Ah | **0.91 Ah** | 40 | 50 / **50** A | **0.83 / 0.83 A** |
| battery-5 | 30p | 28.7 Ah | **0.96 Ah** | 40 | 40 / 100 A | 1.33 / 3.33 A |
| lfp-1 | 16S | 54.8 Ah | — | 0 | 200 / 200 A | — |

Cell over/under-voltage protection **[M]**: NMC 4.19–4.20 V / 2.82–2.90 V, LFP 3.650 / 2.500 V.
Those suit every cell type in the bank, so the one remaining unknown part number blocks
nothing operationally — it matters for lifetime estimates, not for settings.

### State of health, 2026-10-14

A second, better measurement: the bank went from genuinely empty (lfp-1 at
3.017 V/cell on 10-13 07:30) to full, and the charge into each pack was integrated.
**lfp-1 took 239.8 Ah against a 230 Ah nameplate — 104 %** — which makes it a known-good
reference: had the BMS current readings been inflated, the one pack whose true capacity
we know would not have landed on its label. So the NMC figures below are trustworthy to
a few percent.

| pack | charge taken | per cell | est. full | nominal | **SoH** | cycles *here* |
|------|--------------|----------|-----------|---------|---------|---------------|
| battery-1 | 79.0 Ah | 1.80 Ah | 2.56 Ah | 3.0 | **85 %** | 45 |
| battery-5 | 56.3 Ah | 1.88 Ah | 2.68 Ah | 3.2 | **84 %** | 40 |
| battery-3 | 47.9 Ah | 1.60 Ah | 2.28 Ah | 2.9 | **79 %** | 268 |
| battery-4 | 101.3 Ah | 1.69 Ah | 2.41 Ah | ~3.4 | **71 %** | 40 |
| battery-2 | 70.4 Ah | 1.76 Ah | 2.51 Ah | ? | ? | 46 |

Whole bank over that charge: **594.7 Ah / 32.0 kWh in**, of which NMC 354.9 Ah / 18.9 kWh
and lfp-1 239.8 Ah / 13.1 kWh. Usable out is lower, since charging happens at a higher
voltage than discharging — reckon **28–30 kWh**.

- **Assumption that drives the SoH column:** the 3.44 → 4.05 V/cell span is taken as ~70 %
  of a full NMC cycle. Absolute percentages could move ±10 points if that is off, but the
  factor is common to every pack, so the *ranking* is solid.
- **The most worn pack is battery-4, the ex-Tesla cells — not battery-3.** 71 % at 40
  cycles against 79 % at 268. The cycle counter only counts since its BMS was installed,
  and salvaged cells arrive with a history nothing in this system records. Read low cycles
  on a salvage pack as "unknown", never as "young".
- This also finally retires the older claim that the NMC bank is worth 10–12 kWh, roughly
  half its ~26 kWh nominal. Measured, the NMC side alone took 18.9 kWh over ~70 % of its
  range, so it is at **80–90 % of nominal**, not half.

### Using the measurement to identify a cell

The cross-check runs in reverse too, and it is how battery-2 gets narrowed without
opening anything. It measured 2.51 Ah/cell of real capacity. A 25R (2500 mAh) would
imply ~100 % SoH after 46 cycles in a salvage pack — not credible. A 35E (3500) would
imply 72 %, far below its neighbours. A **3000 mAh cell (30Q or 30E) gives 84 %, exactly
in line with battery-1 and battery-5** — so that is what to look for first.

---

## 3. How to read the numbers

**Always normalise by parallel count.** This is the mistake this file exists to prevent:
on raw delivered Ah, battery-3 (25.2 Ah) looks less than half of battery-4 (54.4 Ah), and
with 268 cycles against 40 that reads as a worn-out pack. It isn't. Per cell the whole
bank falls in 0.84–0.96 Ah, and battery-3 sits 8 % under battery-2 *despite six times the
cycle history*. It is the smallest pack, not a spent one — and by the state-of-health
table above it is in better shape than battery-4. CLAUDE.md carried the wrong version of
this until 2026-10-14.

**Cycle counts are not age.** They start when the BMS was installed, so on a pack of
salvaged cells they say nothing about what the cells did before. battery-4 is the proof:
40 cycles, worst SoH in the bank.

**Delivered Ah is not capacity.** It also absorbs internal resistance — a pack that sags
more delivers less over the same bus-voltage window. It measures the operationally useful
thing (what the pack actually contributes), which is not the same question.

**The BMS "cell resistance" is mostly harness, not cells.** Reported averages: battery-1
15.77 mΩ, battery-2 15.96, battery-3 17.68, battery-4 15.87, battery-5 18.40, lfp-1 4.75.
battery-4 is 60p yet reads the same as the 40p packs — if cells dominated it would read
about two thirds of theirs. The measurement runs through the sense wires, so it is
dominated by wiring and contacts. Useful as a per-pack fingerprint and for spotting a
developing bad joint over time; useless as a statement about cell health.

**BMS SoC and `remain_ah` are optimistic** — they derive from the configured nominal
capacity, not the real one. Trust voltage and delivered energy.

---

## 4. Open items

- **battery-4 has the tightest per-cell limits in the bank** (0.83 A both ways, against
  1.25–3.33 A elsewhere) while being the largest and most uniform pack. 50/50 A looks
  copied from a 40p pack. Nothing is near tripping — worst observed is 0.85 A/cell, about
  0.3C — but it inverts the cascade order: the pack that should hold out longest will
  protect first, and whatever drops out hands its current to packs already nearer their
  caps. Raising it is a BMS settings write (registers as per CLAUDE.md), owner's call.
- lfp-1 is set to 200 A both ways. Safe for 230 Ah EVE cells (0.87C, spec 1C) but the
  inverters cap out around 160 A total, so the limit can never be reached — it protects
  nothing. The original plan was 115–150 A.
- battery-3's 30 A charge limit is **deliberate [O]** — 30p means 1.0 A/cell, ~0.3C.
  Leave it.

## 5. Regenerating the numbers

Delivered Ah over an arbitrary window, per pack (run on .224):

```bash
for p in lfp-1 battery-1 battery-2 battery-3 battery-4 battery-5; do
  printf "%-10s " $p
  curl -s -G "http://localhost:8086/query" \
    --data-urlencode "db=invertor" --data-urlencode "epoch=s" \
    --data-urlencode "q=SELECT mean(current_ma) FROM \"bms_$p\" WHERE time > now() - 24h GROUP BY time(5m)" \
  | python3 -c 'import sys,json
s=json.load(sys.stdin)["results"][0].get("series")
print("%+.1f Ah"%sum((r[1] or 0)/1000*(5/60) for r in s[0]["values"])) if s else print("-")'
done
```

Configured limits and protections come from the BMS settings frame (type `0x01`), which
`bms_daemon.py` logs in full hex to `/var/log/bms_daemon.log` on the BMS Pi (192.168.1.225)
whenever it changes. Verified byte offsets, little-endian uint32:

| offset | field | | offset | field |
|---|---|---|---|---|
| 10 / 14 | cell UVP / UVPR | | 78 | max balance current mA |
| 18 / 22 | cell OVP / OVPR | | 114 | cell count |
| 26 | balance delta mV | | 118 / 122 | charge / discharge switch |
| 30 | SOC-100 % voltage | | 126 | balancer switch |
| 38 | request charge voltage | | 130 | nominal capacity mAh |
| 50 / 62 | max charge / discharge mA | | 138 | **balancer start voltage mV** |

Each was confirmed by a diff, not by guesswork — write or change one thing, see which
bytes move. Offset 138 was pinned on 2026-10-14 when it went 3000 → 3400 mV and only bytes
138/139 changed.

**Writing parameters back: unverified, and read this before concluding anything.** The
switch registers 0x1D (charge), 0x1E (discharge) and 0x1F (balancer) are verified and do
take writes. A parameter write (`bal_start:3400`, register 0x22) looked rejected — the
frame still read 3000 afterwards — and that conclusion was wrong: **the frame compared
against had been logged before the write.**

The daemon never requests a settings frame. It sends `0x96`/`0x97` at connect and that is
effectively the only moment a `0x01` frame arrives; a *switch* write makes the BMS push
one unprompted, a *parameter* write seems not to. So after a parameter write the log shows
the old frame indefinitely, and it reads exactly like a rejection.

What actually happened: the write went out at 14:18, the next frame arrived at 18:25 on
reconnect and read 3400, and the owner changed nothing in the app meanwhile. That leaves
the write as the only candidate, so 0x22 probably does work.

**To settle it:** `setreg:22:3410` on `home/bms/<pack>/cmd`, then disconnect + connect the
pack to force a fresh `0x01`, and see whether offset 138 follows. Same method for any
other parameter — the forced reconnect is the part that was missing, not the write.

```bash
ssh pi@192.168.1.225 'grep -a SETTINGS /var/log/bms_daemon.log | tail -40'
```

then decode offsets 50 and 62 from the last frame per pack.
