"""Is the LFP pack converging, or is this permanent? — day by day.

Runs on .224 (where InfluxDB lives), not on the BMS Pi. Reads data the BMS
daemon already records, so it works retrospectively — no new collection needed.

    python3 imbalance_trend.py [pack] [days]

## The question this answers

A cell spread has two very different causes and they look identical on any single
day:

  * **A one-off state-of-charge offset** — the pack was assembled with cells at
    different charge. The balancer moves that charge once and it is gone. The Ah
    it shifts falls each cycle, towards zero.
  * **A capacity mismatch** — some cells simply hold less. They fill first, run
    up the knee first and cap the whole pack. The balancer has to redo the same
    work *every cycle*, because charging pulls the cells apart again. The Ah it
    shifts stays flat, forever. Balancing cannot fix this; it only chooses which
    end of the charge the mismatch shows up at.

So the discriminator is **not** the spread — which is noisy, and on an LFP
plateau is mostly meaningless anyway — but the **charge the balancer moves per
cycle**. Falling means it is converging. Flat means it is structural.

## Reading the output

`bal Ah` is the number to watch across days. `spread` is sampled only near the
knee and at low current, because that is the only place cell voltage maps to
state of charge: on the plateau a few mV is noise plus IR, and during a heavy
charge the spread is dominated by internal resistance rather than charge (on
this pack, ~27 mV of pure IR at 68 A). `top cells` names the cells sitting
highest at the knee — if that set is stable day after day, the same cells are
filling first, which is the capacity-mismatch signature.
"""

import json
import sys
import urllib.parse
import urllib.request
from collections import Counter

INFLUX = "http://localhost:8086/query"
DB = "invertor"

# Sampling window for a meaningful spread: near the top of charge, and with the
# current small enough that IR is not what we are measuring.
KNEE_V_PER_CELL = 3.50
MAX_CURRENT_A = 6.0


def influx(query, epoch="s"):
    url = INFLUX + "?" + urllib.parse.urlencode({"db": DB, "q": query, "epoch": epoch})
    data = json.loads(urllib.request.urlopen(url, timeout=60).read().decode())
    series = data.get("results", [{}])[0].get("series")
    if not series:
        return [], []
    return series[0]["columns"], series[0]["values"]


def main():
    pack = sys.argv[1] if len(sys.argv) > 1 else "lfp-1"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    slots = 16 if pack.startswith("lfp") else 14

    cells = ",".join("mean(cell_%02d_mv) AS c%02d" % (i, i) for i in range(1, slots + 1))
    cols, rows = influx(
        "SELECT %s, mean(total_mv) AS tot, mean(current_ma) AS cur, "
        "mean(balance_current_ma) AS bal FROM \"bms_%s\" "
        "WHERE time > now() - %dd GROUP BY time(5m) tz('Europe/Prague')"
        % (cells, pack, days))
    if not rows:
        print("no data for %s" % pack)
        return

    i_c0 = cols.index("c01")
    i_tot, i_cur, i_bal = cols.index("tot"), cols.index("cur"), cols.index("bal")
    import datetime

    per_day = {}
    for r in rows:
        day = datetime.datetime.fromtimestamp(r[0]).date().isoformat()
        d = per_day.setdefault(day, {"ah": 0.0, "mins": 0, "spreads": [], "tops": Counter(),
                                     "peak": 0.0})
        bal = r[i_bal] or 0
        d["ah"] += abs(bal) / 1000.0 * (5 / 60.0)
        if abs(bal) > 50:
            d["mins"] += 5

        cv = [r[i_c0 + k] for k in range(slots)]
        if any(v is None for v in cv) or r[i_tot] is None:
            continue
        v_cell = r[i_tot] / 1000.0 / slots
        d["peak"] = max(d["peak"], v_cell)
        if v_cell < KNEE_V_PER_CELL or abs((r[i_cur] or 0) / 1000.0) > MAX_CURRENT_A:
            continue
        d["spreads"].append(max(cv) - min(cv))
        mean = sum(cv) / slots
        for k in range(slots):
            if cv[k] - mean > 30:            # clearly in the high group
                d["tops"][k + 1] += 1

    print("%s — balancer throughput per day is the signal; spread is context." % pack)
    print("spread sampled only above %.2f V/cell and below %.0f A.\n"
          % (KNEE_V_PER_CELL, MAX_CURRENT_A))
    print("day          bal Ah   active   peak V/cl   spread at knee      top cells")
    for day in sorted(per_day):
        d = per_day[day]
        if d["spreads"]:
            s = sorted(d["spreads"])
            spread = "%3d mV (n=%2d)" % (s[len(s) // 2], len(s))
        else:
            spread = "  never reached "
        tops = ",".join("c%d" % c for c, _ in d["tops"].most_common(5)) or "—"
        print("  %s %7.2f %6d m      %.3f   %s   %s"
              % (day, d["ah"], d["mins"], d["peak"], spread, tops))

    print("\nFalling bal Ah  -> a one-off offset, it is converging.")
    print("Flat bal Ah     -> a capacity mismatch; balancing re-does it every cycle")
    print("                   and the pack will stay like this.")


if __name__ == "__main__":
    main()
