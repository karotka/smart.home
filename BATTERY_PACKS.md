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

| pack | parallel | chemistry | cell type | wrapper | notes |
|------|----------|-----------|-----------|---------|-------|
| battery-1 | 40p14s **[O]** | NMC 18650 | **LG, exact type [?]** | blue **[O]** | |
| battery-2 | 40p14s **[O]** | NMC 18650 | **LG, exact type [?]** | green **[O]** | |
| battery-3 | 30p14s **[O]** | NMC 18650 | Panasonic, **mixed salvage** **[O]** | | assembled from leftovers, so cells are not one type |
| battery-4 | 60p14s **[O]** | NMC 18650 | Panasonic, uniform **[O]** | | largest and most consistent pack |
| battery-5 | 30p14s **[O]** | NMC 18650 | **LG, exact type [?]** | | |
| lfp-1 | 16S **[O]** | LiFePO4 | EVE LF230, 230 Ah **[O]** | | prismatic, not 18650 |

Total NMC cells: 14 × (40+40+30+60+30) = **2800**.

### Still to establish [?]

1. **battery-1 / battery-2 / battery-5 — the LG part number.** Candidates and their
   nominal capacity: MJ1 3500 mAh, GA 3500, M26 2600, HG2 3000, HE4 2500.
2. **battery-4 — the Panasonic part number.** NCR18650B 3400, NCR18650GA 3500,
   NCR18650PF 2900.
3. **battery-3 — what the mix actually contains**, at least roughly. Being salvage, a
   single part number may not exist; "mostly X with some Y" is a useful answer.
4. **BMS board serials.** The JK device-info frame (type `0x03`) carries vendor id,
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
| battery-1 | 40p | 41.6 Ah | **1.04 Ah** | 45 | 50 / 100 A | 1.25 / 2.50 A |
| battery-2 | 40p | 35.1 Ah | **0.88 Ah** | 46 | 50 / 100 A | 1.25 / 2.50 A |
| battery-3 | 30p | 25.2 Ah | **0.84 Ah** | **268** | 30 / 100 A | 1.00 / 3.33 A |
| battery-4 | 60p | 54.4 Ah | **0.91 Ah** | 40 | 50 / **50** A | **0.83 / 0.83 A** |
| battery-5 | 30p | 28.7 Ah | **0.96 Ah** | 40 | 40 / 100 A | 1.33 / 3.33 A |
| lfp-1 | 16S | 54.8 Ah | — | 0 | 200 / 200 A | — |

Cell over/under-voltage protection **[M]**: NMC 4.19–4.20 V / 2.82–2.90 V, LFP 3.650 / 2.500 V.
Those suit both LG and Panasonic 18650s, so the unknown part numbers block nothing
operationally — they matter for lifetime estimates, not for settings.

### Cross-check once a cell type is known

0.84–1.04 Ah/cell came out over roughly 3.79 → 3.45 V/cell, which is only part of the
usable range — call it 35–45 % of a full 18650 cycle. That implies something like
**2.2–2.9 Ah/cell of real capacity**, i.e. aged cells of 3.0–3.5 Ah nominal. A candidate
part number whose nominal is far outside that (an M26 or HE4 at 2.5–2.6 Ah) would be hard
to reconcile with the observed delivery and is probably the wrong guess. Treat this as a
sanity filter, not a measurement.

---

## 3. How to read the numbers

**Always normalise by parallel count.** This is the mistake this file exists to prevent:
on raw delivered Ah, battery-3 (25.2 Ah) looks less than half of battery-4 (54.4 Ah), and
with 268 cycles against 40 that reads as a worn-out pack. It isn't. Per cell the whole
bank falls in 0.84–1.04 Ah, and battery-3 sits 8 % under battery-2 *despite six times the
cycle history*. It is the smallest pack, not a spent one. CLAUDE.md carried the wrong
version of this until 2026-10-14.

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
whenever it changes. Verified byte offsets, little-endian uint32 unless noted: 10/14 cell
UVP/UVPR, 18/22 cell OVP/OVPR, **50 max charge mA**, **62 max discharge mA**, 114 cell
count, 118 charge switch, 122 discharge switch, 126 balancer switch.

```bash
ssh pi@192.168.1.225 'grep -a SETTINGS /var/log/bms_daemon.log | tail -40'
```

then decode offsets 50 and 62 from the last frame per pack.
