# smart.home — orientation for a new session

Personal home-automation system: a FastAPI web UI + a heating-control daemon + several
data-collector daemons, plus ESP8266/ESP32 firmware for the physical sensors/relays.
This file is the map so you don't have to re-scan the repo. Detailed proxy/TLS docs live
in **`servers.conf/README.md`** — read that for anything about nginx, the Cloudflare
tunnel, or certs.

## Hosts & network

| Host | Addr | Role |
|------|------|------|
| **home** | `192.168.0.224` (Ubuntu 24.04, amd64) | **Everything runs here**: web app (Docker), all daemons, Redis :6379, Mosquitto :1883 + :8884(WS), InfluxDB :8086, Grafana :3000, Frigate NVR :5000. SSH `karotka@192.168.0.224` (sudo pw `aaa`). |
| **cml** (Pi4) | `192.168.0.222` (Raspberry Pi OS) | Legacy front door — nginx + Cloudflare tunnel only. **Being retired**: the proxy layer is now mirrored onto .224 (both tunnel connectors live). SSH `pi@192.168.0.222` (passwordless sudo). |
| BMS Pi | `192.168.1.225` | Runs `bms.monitor.pi` BLE daemon. |

**Entry paths** (detail in `servers.conf/README.md`): remote `home.karotka.cz` / `panel.karotka.cz`
via Cloudflare tunnel → nginx :80 (basic-auth; LAN `192.168.0.0/16` skips it); LAN direct
`pi.karotka.cz` :443 (Let's Encrypt via acme.sh). No router port-forward — the tunnel is outbound.
Access is **mobile-only now** — the old Pi4 wall-display/kiosk is dropped.

> **Server is the source of truth.** .224 often has uncommitted WIP and may be ahead of this
> clone; `checkerd.py` live-reloads `checker.py` each tick, and the container **bind-mounts the
> source**, so edits on .224 take effect without a rebuild. Check the server before assuming.

## (A) Server app + daemons (on .224)

### `web/` — FastAPI UI + heating daemon (Python 3.11, one Docker container)
- **Web entry:** `web/server_fastapi.py` (`app = FastAPI(...)`). WebSocket JSON-RPC at
  `/websocket` dispatches `{method, router, id, params}` → `web/methods.py`. Templates in
  `web/templ/`, static in `web/static/`. `web/server.py` (Tornado) is legacy — ignore.
- **Heating daemon:** `web/checkerd.py` — a foreground `while True:` loop (NOT systemd/cron)
  that `importlib.reload(checker)` and runs `checker.Checker(logger).check()` every ~1 s.
  All heating/solar-boost logic is in **`web/checker.py`**. Because of the reload, editing
  `checker.py` on the server takes effect next tick — no restart.
- **How both run:** `web/run.sh` launches gunicorn (`--workers 4`, uvicorn workers,
  `0.0.0.0:8000`, `server_fastapi:app`) in the background, then `checkerd.py` in the
  foreground. One container = web + heating daemon.
- **Deploy (no docker-compose):** `web/Dockerfile` (`python:3.11-slim-bookworm`, EXPOSE 8000,
  `CMD run.sh`). `web/Makefile`: `make build`, `make run` =
  `docker run -d --restart=always -p 8001:8000 -e TZ=Europe/Prague -v $(pwd):/root/project --name smart-home smart-home:latest`.
  **Host 8001 → container 8000**; the source is bind-mounted at `/root/project` (live code).
  `make enter` for a shell. The `karotka/*` registry image is legacy arm/v7 — build locally on .224.
- **Config:** `web/conf/config.ini` (via `web/config.py`). Contains **Tuya local_keys — never
  commit changes with those** (gitignored artifacts exist). Sections: `[Db]` Redis, `[Mqtt]`,
  `[Influx]` (db `invertor`, hpDb `hp`), `[Heating]` + `[HeatingSensors]` (sensor↔room↔manifold-port
  map; manifold ESP at `192.168.0.5`, heating relay at `192.168.0.6`), `[Lights]`, `[Blinds]`
  (Tuya ids/keys), `[Battery]`.
- **Deps:** `web/requirements.txt` (fastapi, uvicorn, gunicorn, jinja2, redis, pandas<2,
  numpy<2, influxdb 5.3, tinytuya, paho-mqtt<2, python-daemon).
- **Helper services** (`web/service/*`): `lights_poller.service` (caches switch states into
  Redis `light_state_<id>`); `tuya_rediscover.service` + `.timer` (hourly, refreshes Tuya LAN
  IPs into snapshot.json); `web/mqtt_bridge.py`.

### Other collector daemons
- `invertor/` — PIP solar-inverter monitor over RS232. `invertor/invertor.py` → InfluxDB
  db `invertor` + Redis + MQTT. Also `mqtt.feeder.py`, `tuya.py`, `aggregate.py` (roll-ups).
  Units in `invertor/service/`.
- `heatpump/` — Tuya heat-pump monitor. `heatpump/hp_monitor.py` (tinytuya) → InfluxDB db `hp`.
  Unit `heatpump/service/hp.service`. Web controls it via `heatpump_*` methods.
- `bms.monitor.pi/` — battery BMS BLE central, runs on the **BMS Pi (.1.225)**.
  `bms_daemon.py` → `bms-monitor-pi.service`. Talks to JK BMSes over BLE; publishes
  `home/bms/<battery-N>/snapshot` (~1 s).
- `crond/cron` — host crontab (invertor roll-ups, log truncation, 6-h service restarts).
  Note: paths there reference `/home/pi/...` (Pi4-era) — verify per host.

## (B) Data plane

- **MQTT** (`.224:1883`, WS `:8884` proxied at `/mqtt`): `home/invertor/{actual,snapshot,daily/rows,monthly/rows}`,
  `home/temp/sensor/+`, `home/bms/<battery-N>/snapshot`.
- **InfluxDB** (`.224:8086`): db **`invertor`** (live + `invertor_daily`/`invertor_monthly` +
  `bms_battery-N`), db **`hp`** (heat pump). Mostly influxdb v1 client.
- **Redis** (`.224:6379`): live state — `light_state_<id>`, `heatpump_status*`, heating
  targets `heating_<roomId>`, `__heatingCounter`, etc.

## (C) Device firmware (ESP8266/ESP32, C/C++ Arduino) & misc

Firmware dirs (flashed to MCUs, not run on servers): `bistable.relay` (relay node),
`blind` (roller blinds), `manifold.switch` (underfloor manifold valves), `temp.sensor` +
`temp.sensor.mqtt` (temp nodes), `energy.meter.6914`, `helioset` (ESP32 solar-thermal),
`stove.regulator`, `bms.monitor` + `bms.monitor.ble` (ESP BMS readers),
`generic.temp.sensor` (Tasmota-script). Build: Arduino+Makefile or PlatformIO (`platformio.ini`).
Shared: `bk/` (ESP wifi/config C++ lib), `tuya/` (Tuya CLI scripts), `mqtt.js.client/`
(browser MQTT dashboard), `influx/` (InfluxDB container), `pi.server/` (enclosure CAD).

## The tablet dashboard
`web/templ/tablet.html` — standalone dashboard (Dashboard / Ovládání / Baterie / Alerty / Radar
tabs), built as a fullscreen PWA on `panel.karotka.cz`. Served by `/tablet.html` in
`server_fastapi.py`; own manifest/service-worker (`manifest.tablet.json`, `sw-tablet.js`). Mobile
pages keep their own separate templates.

## Temp sensors (ingest gotcha)
ESP temp sensors do `GET /sensorTemp?id=&t=&h=&p=&v=&s=&r=` → the app builds a reading and
publishes `home/temp/sensor/<id>` (retained) → `mqtt_bridge.py` (a plain python3 proc on .224,
subscribes `home/temp/sensor/+` and `home/invertor/snapshot/+`) writes Redis `temp_sensor_<id>`
→ `heating_SensorRefresh`/`checker` read those. **The sensors' endpoint IP is 192.168.0.222:8000
baked into their firmware** — it used to be the Pi4. When .222 was retired (2026-09-30) all live
sensors went stale (heating ran on ~2-day-old temps). Fix: **.224 took over .222's IP + port 8000**
(`servers.conf/sensor-ip.service` adds 192.168.0.222/23; `servers.conf/sensor-ingest` nginx `:8000`
→ `127.0.0.1:8001`). So **.222 must stay OFF** (IP conflict otherwise). To check sensor health, read
`temp_sensor_*` from Redis and compare each `updated_ts` to now — stale = that ESP node is offline.
As of the fix, 6 sensors live; 4 long-dead ESP nodes (garaz, sklenik, petr, sid 10202255) need
physical attention. `updated_ts` is the freshness field; `sid 99999`/`T=200` was a bogus test entry.

## Alerting
`web/alerts.py` evaluates rules from **`web/conf/alerts.json`** every ~15 s inside `checkerd`
(isolated try/except — never blocks heating), writing the result to Redis `alerts_view`.
`methods.alerts_status` just reads that back for the **Alerty** tab (header badge + severity cards).
Rules are declarative (`scope: per_pack`, ANDed `conditions`, `hold_s` before firing) and
**mtime-reloaded — edit thresholds in alerts.json, no restart**. v1 = battery/BMS only
(SOC, cell imbalance, over/under-voltage, temp, charging-in-frost, pack offline); packs are
14S LiPo (cell over/under-voltage 4250/3000 mV). Adding a category = add rules + extend the signal source in `alerts.py`
(currently `_battery_signals()` from `battery_packs()`). **Note:** a new `methods.py` method or
non-template code change needs a container restart (`docker restart smart-home`) — checkerd only
live-reloads `checker.py`/`alerts.py`, and gunicorn imports `methods` once.

## Battery, solar & heat-pump energy system

**Battery bank (DC-coupled, shared bus):** 5× **14S NMC** packs (Tesla/Panasonic 18650), each
with its own **JK BD6A24S10P** BMS (24S-capable), paralleled on the DC bus. Nominal ~511 Ah /
~26 kWh, **but a real overnight test (2026-09-21) showed only ~7 kWh took the bank ~78%→~18%
(55.4→48.0 V, i.e. 3.43 V/cell = the user's "3.4 V"), so REAL usable ≈ 10–12 kWh — roughly HALF
the nominal.** The JK **`remain_ah`/SoC readings are optimistic** (configured nominal, not true
capacity) — trust voltage + delivered energy, not BMS SoC. Cells stay balanced (~30 mV spread),
so it's capacity fade + aged **battery-3** (257 cycles vs ~30), not a fault. Live per-pack data:
`methods.battery_packs()` (InfluxDB `bms_battery-N`) + MQTT `home/bms/<battery-N>/snapshot`.
Deep-discharge floor: NMC is fine to ~44 V (3.14 V/cell, ~5%); **with the LFP in parallel don't
take the bus below ~42–43 V** (16S LFP hits its 2.5 V/cell floor) — 44 V = LFP 2.75 V/cell (empty
but safe). Strategy once LFP is in: be gentle on the NMC (~46 V floor) and take the deep tail
from the LFP instead.

**Expansion in progress (LFP ordered 2026-09):** adding **1× 16S LiFePO4** pack from **EVE
LF230** cells (3.2 V nom / 3.65 V charge / 2.0 V cutoff, 230 Ah, 1C max, 8000 cyc) ≈ **11.8 kWh**,
own BMS, parallel on the same bus. Plus **9×450 W (4 kWp) PV vertical on the fence, due south**
— vertical beats the shallow 17° roof for the low winter sun (solar noon only ~16° at 50.13°N;
vertical captures ~96% of the beam vs ~55% for the 17° roof → ≈+74% in December). Roof stays for
summer; the two orientations are complementary. Bifacial worth considering (snow albedo).

**Mixed-chemistry parallel is OK here** (revised from an earlier flat "no"): a shared bus = one
shared voltage, and each pack's own BMS protects its own cells. A shared window **~57.7–46 V**
keeps both chemistries inside per-cell limits — 14S NMC 4.12→3.29 V/cell, 16S LFP 3.606→2.875
V/cell; full-charge voltages nearly coincide (58.8 vs 58.4 V). Current is NOT the constraint:
inverters cap ~140–160 A (+ new PV ~70 A ≈ 210 A total) vs LFP 1C = 230 A — just give the LFP
BMS a sane limit (~115–150 A). LFP's flat curve makes it hog mid-range current, but that's moot
at these real currents.

**Inverters:** 2× PIP/MPP-style units, each a **Raspberry Pi running `invertor.py`** with a USB-serial
link to its inverter, reachable **only via SSH-jump from .224** (they sit on 192.168.**1**.x, /23 with
.224): **192.168.1.225 = `invertor-first` = inv1** (redis `invertor_1`), **192.168.1.223 =
`invertor-second` = inv2** (`invertor_2`). Managed by systemd (`invertor-first/second.service`), config
at `/home/pi/smart.home/invertor/conf/config.ini`, logs `invertor/log/invertor_{first,second}_log`.
They feed InfluxDB db `invertor` (`invertor_status` = config, `invertor`/`invertor_actual` = live,
`invertor_daily`/`_monthly` = aggregates); heat-pump data is in db `hp` (field `power`). Config: output
priority **SOL** (Solar→Utility→**Battery last** — why the battery is barely cycled in winter), charging
**OSO** (solar-only), input range **ALP** (Appliance), float 57.7 / bulk 57.8 / mains-switch 47 /
shutdown 45.5 V, solar charge 70 A/unit.

**Inverter findings (2026-09-24):**
- **Parallel setup + master/slave:** the two units ARE a parallel pair (Program 28 = PAL on both,
  joined 230 V output, ~50/50 load share). **Master = inv1 (`first`, 192.168.1.225); Slave = inv2
  (`second`, 192.168.1.223)** — confirmed by powering the slave off: the master alone held 229 V/50 Hz
  and the whole load. BUT the firmware doesn't expose parallel status over the protocol: **QPGS0/QPGS1
  return NAK and QPIRI reports parallelMode = 0 (NP)** even though it's PAL — an incomplete-firmware quirk.
- **Charge-current taper & the asymmetry:** `invertor.py` sets max charge current by battery voltage
  each minute (`setChargeCurrent`, config `[Charge] stages`). In parallel, only the **master's** `MNCHGC`
  takes effect; the **slave ignores its own** and the master's value doesn't propagate to it, so the slave
  sits at 70 A. The old taper (`57.0:10…`) throttled only the master below the slave → that was the "one
  inverter idle, one working, running hot" asymmetry. **Fixed: taper neutralized to `stages = 60.0:70`
  (always 70 A) on both** so the master matches the slave; the CV voltage (57.8/58.0) does the top-off.
  To actually *limit* charge current, set it on the **master's panel** (Program 02), not per-unit via
  the daemon.
- **Restart wedges the USB-serial → needs reboot (BOTH Pis):** `systemctl restart` of an invertor daemon
  leaves the serial in an `ERROR data: <['']>` reconnect loop; **only `sudo reboot` of that Pi clears it**
  (the inverter keeps running physically — only monitoring/control drops). Root cause: systemd's SIGTERM
  terminates the process without running `main()`'s `finally`, so the serial is never closed and the cheap
  USB-serial adapter stays wedged until a reboot re-enumerates it. **FIXED 2026-09-25 (commit 08aa427):**
  `invertor.py` now traps SIGTERM/SIGINT → SystemExit so `main()`'s finally runs and closes the serial
  cleanly. Deployed to both Pis; **verified on the master that `systemctl restart` now recovers without a
  reboot** (clean stop "Serial port closed cleanly" + clean start, no ERROR loop). The old reboot dance is
  no longer needed. (`ExecStartPre` usbreset was the fallback — not needed, the handler was enough.)
- **Inverter-vs-BMS voltage offset:** the inverter senses battery voltage HIGHER than the BMS pack
  reads. Fitted over 24 h: **offset = 6.0 mΩ × I + 0.20 V** → ~**0.20 V constant calibration** + a
  **6 mΩ IR drop** across the busbar/joints (system busbar is 4×30 mm Cu — the 6 mΩ is in the
  joints/fuses/contacts, not the bar; accepted, won't be reinforced). At ~50 A charge the two sum to
  ~0.5 V, so **the pack never reaches the 57.7 V float** (tops out ~57.2 V charging, ~57.6 V at taper).
  Harmless (gentle undercharge for NMC) but costs a little capacity. **FIXED 2026-09-25:** raised bulk/float
  by +0.2 V on the master via serial (`PCVV58.0` / `PBFT57.9`); **it propagated to the slave over the PAL
  link**, so both now read bulk 58.0 / float 57.9 and the pack reaches ~57.7 V at end of charge. Safe (no
  overshoot: at low current pack = setpoint − 0.2 calibration). The 6 mΩ IR part is left as-is. NB: charging
  voltages ARE dictated by the master in PAL (unlike per-unit charge current), which is why the serial set
  on the master alone sufficed.

**Recurring blackout + fault logging (2026-09-27):** the whole off-grid system (both inverter Pis
AND .224) blacks out & reboots roughly weekly. Ruled out: **not battery depletion** (daily min V is
~48–50 V, never near the 45.5 V cutoff), **not overload** (right before the last trip: battery FULL
57.8 V, load only 40%, midday), **not grid** (grid is physically disconnected — pure off-grid). So it's
a **sudden protection trip of the parallel pair** at a healthy moment — cause not yet known (candidates:
momentary inrush overload e.g. the DHW electric spiral kicking in, over-temp, or a parallel master/slave
comms glitch). DHW is NOT on the heat pump (it's thermal-solar + an occasional electric spiral); the HP
is space-heating only (started ~Sep 1). **To catch the cause, added black-box fault logging** (commit
ef063fd, deployed both Pis): each cycle queries **QPIWS** (warning/fault bit-field) + logs it on change,
plus logs any non-normal QMOD device mode → the next trip should log WHY (overload / over-temp / bus /
MPPT / fault). Check `invertor/log/invertor_{first,second}_log` after the next blackout (grep -a; the
logs contain NUL bytes from prior hangs). Note QPIWS bit 5 "Line fail" is filtered out — it's
permanently set because the grid is intentionally disconnected (off-grid).

**Robustness fixes DONE (2026-09-27, commits f... / 05427b1):** the two failure modes are fixed on
both Pis, so a daemon restart no longer needs a reboot and an outage no longer freezes monitoring:
- **Serial read-timeout + self-recovering loop** (`invertor.py`): the port now has `timeout=2`, `call()`
  returns `['']` on a timeout instead of blocking/crashing, `refreshData` raises on a short frame, and
  `run()`'s loop skips+retries a bad cycle. So after a power cut the daemon retries until the inverter
  responds instead of hanging forever on a blocking read.
- **`ExecStartPre` usbreset** (`invertor/reset_usb.sh` + systemd drop-in `invertor/service/usbreset.conf`
  → `/etc/systemd/system/invertor-{first,second}.service.d/usbreset.conf`): each start re-enumerates the
  CH341 USB-serial adapter (`usbreset`, run as root via `+`, ignore-fail via `-`) so the stochastic wedge
  clears without a reboot. Verified on both: `systemctl restart` now resets the adapter and comes up clean.
The CH341 adapter is the culprit chip; `sudo reboot` of a Pi is still the last-resort recovery but should
no longer be needed for routine restarts.

**LIKELY BLACKOUT CAUSE FOUND — EEPROM wear (2026-09-28, commit a766212):** the black-box QPIWS
logging caught the smoking gun — before the outages, **both inverters set QPIWS bit 17 "EEPROM
fault" ~3 min before the blackout** (seen 09-27 and again 09-28 10:27/10:28 → 10:31 outage). Root
cause: `setChargeCurrent` wrote `MNCHGC` (charge current) to the inverter **every minute even when
unchanged** (~1440 EEPROM writes/day/inverter) → EEPROM wear → EEPROM fault → inverter reset →
whole-system blackout (both inverters, no overload/depletion/over-voltage, grid disconnected — all
consistent). **Fixed:** MNCHGC is now written only on an actual value change (verified: after
restart it wrote once at 12:46 and stopped, vs. every minute before). The user physically measured
the DC connections — they're fine, which rules out the intermittent-joint theory and fits EEPROM
wear instead. **Watch:** if the outages stop (and QPIWS bit 17 no longer appears), confirmed. If they
continue, the EEPROM may already be degraded, or it's the parallel interaction — fallback test:
**run only ONE inverter** (master inv1/.225, slave off); outages stopping → parallel/slave, continuing
→ the running unit / a common cause.

**ACTUAL BLACKOUT CAUSE — parallel CAN comm fault F80 (2026-09-28, supersedes EEPROM theory):**
when the slave was caught live in fault mode, its **panel showed code F80 = CAN / parallel
communication fault**, and its log had "Inverter fault" (QPIWS bit 1 + a high parallel bit) →
mode F → ~90 s later the whole system blacked out. So the recurring outage is the **parallel
communication link between the two inverters intermittently dropping** (F80): the slave faults →
the parallel output collapses → blackout/reboot. The earlier "EEPROM fault" (QPIWS bit 17) was a
misleading/secondary signal — F80 off the panel is definitive. Data right before a crash is calm
steady-state (battery FULL at 57.9 V float, trickle 8 A, load 1–2 kW, temp 47–50 °C) — **no
electrical trigger**, which is exactly how an intermittent CAN link behaves (fine for hours, then a
random dropout). Every crash so far is at full-battery/float (when both units curtail solar and
coordinate current-sharing over CAN — CAN-heavy, so a marginal link is most exposed). **Fix
(physical, user doing it):** replace the parallel comm cable + route it AWAY from the high-current
DC/AC bundle (induced noise into CAN is the classic cause); check connectors/termination; if the
cable's clean, the slave's CAN port may be failing. **Update 2026-09-28:** the user says the cabling
is already replaced/rerouted, yet F80 still recurs → so it's NOT the cable. Firmware checked via
serial (QVFW): **both inverters are on the same version VERFW:00072.10** (no mismatch; QID reads a
generic "5535…" on both). So the remaining causes are (a) a parallel/CAN **firmware bug in 72.10**
(both units) — check the vendor for a newer firmware with parallel fixes; or (b) a **CAN hardware
fault at one unit** (slave always the one that faults → its CAN receiver, or the master's CAN
transmitter). **Localize:** physically swap the two units — if F80 follows a specific physical unit
→ that unit's CAN hardware (service/replace); if it stays on the slave role → firmware. (QPGS over
serial always NAKs on this firmware even when the parallel is healthy — not a fault signal.) Running one inverter isn't a long-term option
(5 kW ≠ whole house). Note: crashes got more frequent after per-second QPIWS polling was added
(09-27) — almost certainly coincidence (QPIWS is on the serial port, not CAN), but QPIWS was
throttled to 30 s (commit 94e237c) to rule it out. The MNCHGC-write-on-change fix (a766212) stays
regardless (less EEPROM wear).

**Energy reality (winter, from data):** the **heat pump is ~80% of consumption** (~15–16 kWh/day,
overnight 17–08h ~6–8 kWh); house ~19 kWh/day, winter solar 6–10 kWh, ~10 kWh/day from grid.
Overnight-with-TC need ≈ 8–10 kWh. **The bottleneck is winter recharge, not storage** (battIN
only 2–4.5 kWh/day — not enough surplus solar); multi-day dark spells (solar ≈ 0) still need grid.

**Plan / order of operations:** fit LFP + vertical PV → **then switch inverter output priority
SOL→SBU** (Solar→Battery→Utility) so the battery actually covers the night; keep OSO (optionally
allow limited grid charging in deep winter as a safety floor against a low battery on an unstable
grid). Target ≈ 34 kWh usable ≈ 2–3 nights of TC autonomy. Past "flapping to a low battery on a
wobbling grid" was grid quality, not a bad setting (input range already Appliance) — more
capacity + PV fixes it by keeping the battery off empty. After LFP is in, give the alert rules
**separate NMC vs LFP per-cell thresholds** (NMC 4.15/3.0 V, LFP 3.65/2.5 V) — `alerts.json` is
already per-pack.

## Heat-pump control (checker.py, runs every tick)
- **Night / day-quiet / day-full schedule** (`checkHeatingSchedule`): priority is **charging the
  battery**, so the HP runs gentle by default and only ramps up when the battery is genuinely charging:
  - `night` (≥21:00 or <07:00) → **32 °C + "mute"**.
  - `day_quiet` (daytime, battery **not charging** — no real sun yet / overcast) → **32 °C + "mute"**.
    Priority is charging: while the battery isn't charging we keep the low night target so the HP
    doesn't ramp up and drain the pack off-solar (a cold dark morning stays gentle until the sun
    catches up). It raises to the day target only once the battery is genuinely charging (`day_full`).
  - `day_full` (daytime, SoC ≥ 80% **and** battery charge current ≥ `DAY_HP_CHARGE_MIN_A` **and** not
    discharging) → **37 °C + "smart"**.
  The charge/discharge gate is on the **battery charge current** (`batteryCurrent` summed over both
  inverters), NOT raw PV watts — "the sun is up" isn't enough, the pack has to actually be gaining.
  Hysteresis (hold `day_full` to SoC-15 / discharge ≤ `DAY_HP_DISCHARGE_MAX_A`) + a dwell throttle
  (`HEATING_SCHED_INTERVAL`, 300 s) stop clouds from flapping the mode; the evening/morning night flip
  is never throttled. Tunables: `NIGHT_HP_*` / `DAY_HP_*` / `HEATING_SCHED_INTERVAL`. State in Redis
  `heating_sched_mode` (`night`/`day_quiet`/`day_full`) + `heating_sched_ts`.
- **Solar boost** (`checkSolarBoost`): layers on top — **engages only when the battery is charging ≥
  `SOLAR_BOOST_CHARGE_MIN_A`** (15 A) at SoC ≥ 85% (genuine surplus, so the 50 °C TC won't drain the
  pack), bumps the target to 50 °C, and **releases the moment the battery starts discharging** (> 1 A)
  — charging has priority. On release it falls back to the schedule's current base (32 night / 37 day),
  not a stale snapshot. Skips the schedule while boost is active so they don't fight. (Old SoC-only
  engage + 3-miss hold is gone — it used to drain the pack for ~30 min after a false engage.)
- HP water target = PG1[4] via `__setHeatingTarget` (write-on-change; also syncs the
  `heatpump_status_heating_target_water_temp` Redis cache the UI reads). Mode via `heatpump_setMode`
  ("smart"/"mute"/"strong"). Note `heatpump_status.targetTemp` reads that cache, not live PG1 — it can
  lag until a write or an HP-page load resyncs it.

## Gotchas
- **No docker-compose**; deploy is the `web/Makefile` `docker run` with a live bind mount.
- Several `crond/cron` and `*.service` files hardcode `/home/pi/smart.home/...` (Pi4 paths) and
  a few have typos — **verify a unit before trusting/enabling it.**
- The heating decision in `checker.py` only acts when a room's `heating_direction == "heating"`;
  config `hysteresis` exists but isn't applied. The daemon is hardened so a hung manifold
  (`192.168.0.5`) no longer blocks the heating relay (`192.168.0.6`).
- Repo is public — do not commit secrets (Tuya keys, tokens, htpasswd, certs).
