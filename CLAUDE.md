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
  ⚠ The reload covers `checker.py` and nothing it imports. `importlib.reload(checker)`
  re-executes that module, but `import utils` then finds utils already in `sys.modules` and
  skips it. So a change that touches **both** files leaves a new `checker.py` calling an old
  `utils.py`, and the daemon throws `AttributeError` on every tick until the container is
  restarted — 28 ticks of it on 2026-10-25 between the `git pull` and the restart. Pull and
  `docker restart smart-home` in one go whenever anything but `checker.py` changed.
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
  **Deployed as a loose copy at `/home/pi/bms_daemon.py` (NOT the git checkout)**, venv
  `/home/pi/bms/bin/python`, logs to `/var/log/bms_daemon.log` (not journald). Talks to JK
  BMSes over BLE; publishes `home/bms/<pack_id>/snapshot` (~1 s). Packs are listed in
  `PACKS_DEFAULT` (5× 14S NMC `battery-1..5` + 16S LiFePO4 **`lfp-1`**).
  - **Frame types:** `0x02` = cell info (live), `0x01` = **settings**, `0x03` = device info.
    The MOSFET switch states live in the **settings** frame, not cell info — that's why
    `charge_mos`/`discharge_mos` were a hardcoded `False` stub for so long.
  - **Settings audit log:** any change to a pack's settings frame logs the full 300-byte hex
    (`[pack] SETTINGS <hex>`). Compare byte-for-byte to see exactly what moved — ours, the JK
    app's, or the BMS's own. (Byte 5 is a frame counter and 299 a crc; both always change.)
  - **MOSFET control** via `home/bms/<pack>/cmd`: `charge_on` | `charge_off` |
    `discharge_on` | `discharge_off` (plus the older `connect`/`disconnect`, which only
    pause the BLE link so the JK phone app can take over). Writes go to registers
    **`0x1D` (charge)** and **`0x1E` (discharge)**, verified 2026-10-12 on `lfp-1` by diffing
    the whole settings frame before/after: **only byte 118 / 122 changed** (plus counter and
    crc) — every protection threshold untouched — and the charge current physically went
    4.94 A → 0 → 4.94 A. Verified offsets: 114 cell count, 118 charge sw, 122 discharge sw,
    126 balancer sw; 10/14 cell UVP/UVPR, 18/22 cell OVP/OVPR, 50/62 max charge/discharge mA.
- **`invertor/tuya.py`** (`tuya.service` on .224) — **the grid breaker**. Subscribes to MQTT
  `home/invertor/actual/` and once a minute switches the Tuya breaker **"Solar in"**
  (`bf804257239825cfb7xyjf`, category `dlq`) by battery voltage: **> 53.5 V → open (ČEZ
  physically disconnected), < 52 V → close**, in between unchanged. That is a *physical*
  disconnect, separate from and upstream of the inverters' own SBU/SOL priority — with it open
  the inverters report `gridVoltage 0`. One cycle a day is the expected rhythm (it opens once
  solar has lifted the pack over 53.5 and closes when it falls under 52; SBU then keeps using
  the battery down to the inverters' own 47 V transfer point, so it does not chatter).
  - ⚠ **The device will not take a static IP and DHCP moves it.** The address used to be
    hardcoded and when the device moved .166 → .172 the breaker stayed closed from 2026-10-11
    to 10-21 while the script decided to open it once a minute and died on
    `data.get("dps").get("1")` — the traceback went into a log nobody reads (82 MB of it).
    It now resolves ip+key from `web/conf/snapshot.json` (which `tuya_rediscover.timer`
    refreshes hourly) and falls back to a `find_device` broadcast, so a move self-heals in
    one cycle. An unreadable breaker is treated as *unknown* and left alone, never as "off".
  - ⚠ **Since 2026-10-22 07:00 the device is off the air entirely** — it does not ping, does
    not answer on 6668 and does not show up in the `tuya_rediscover` broadcast scan, so this
    is the device, not the address. `tuya_log` has nothing but `Err 901/905` since then. The
    safe branch holds (breaker left as-is, physically closed), so the grid stays connected
    above 53.5 V — no export protection until the switch is replaced.
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
- **`gridmeter/`** — reading the KLEFR 6914 (= rebadged Inepro PRO1-Mod) kWh meter in the
  grid feed over Modbus RTU, so grid import is *measured* instead of derived from the energy
  balance. **`gridmeter/esp/wiring.md` is the full schematic** — battery bus → PTC → DCE003
  → ESP32 → MAX485 → meter, capacitor values, which GPIOs are safe on WROOM vs WROVER, and
  why only A/B cross between cabinet and board. `gridmeter/esp/` is the ESP32 firmware
  (9600 **8E1**, DE/RE on GPIO4, MQTT `home/grid/meter/snapshot`); `gridmeter/probe.py` is
  the Modbus prober for pinning down the register map. Only voltage and total energy
  (`0x6000`, float32) are confirmed; the rest is PRO1-family convention.
  - The older `energy.meter.6914/` is a **failed 2026-07 attempt** on an ESP8266 — it polled
    decimal holding registers 4003/4004 (PRO380 numbering) and never read anything. Keep it
    only as history; the Inepro doc numbers registers in hex.
Shared: `bk/` (ESP wifi/config C++ lib), `tuya/` (Tuya CLI scripts), `mqtt.js.client/`
(browser MQTT dashboard), `influx/` (InfluxDB container), `pi.server/` (enclosure CAD).

## ⚠ `mqtt.js.client` is served from /var/www, not from the checkout
`solar_chart.html` is a thin page whose body is an iframe to `/mqtt.js.client/`, and nginx
aliases that to **`/var/www/mqtt.js.client`** (`sites-available/default` and `pi.karotka.cz`) —
a manual copy of the repo directory. Editing `mqtt.js.client/index.html` in the checkout changes
nothing until it is copied over, and the copy needs sudo. Checking with `curl localhost` is
misleading too: localhost is outside the `192.168.0.0/16` basic-auth exemption, so it answers 401
and a grep for your change finds nothing whether or not it deployed. Fetch `http://192.168.0.224/…`
instead.

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

## Solar forecast (added 2026-10-13)
`web/forecast_solar.py` → retained MQTT **`home/forecast/solar`**, run hourly by
`web/service/forecast_solar.{service,timer}` (installed in `/etc/systemd/system/` on .224).
Pulls Open-Meteo (free, no key): daily outlook ±few days plus **hourly tilted irradiance**
(`global_tilted_irradiance`, tilt/azimuth from config) and converts it with one fitted number,
`factor` = kWh per kWh/m² of plane-of-array irradiance. The tablet's **Solár** panel has a third
chart mode **Předpověď** (`drawForecast()` in `tablet.html`) drawing today+tomorrow as a curve,
with today's measured harvest overlaid.
- **`factor` is the 80th percentile of daily ratios, NOT the mean — deliberately.** The inverters
  are demand-following, so on the brightest days they curtail and the measured ratio comes out
  *low* (observed 2026-10: 7.7 on the clearest days vs ~13.8 on overcast ones). Averaging would
  forecast the curtailment back at us. So the published curve is **potential**; `actual_kwh` /
  `act_kw` next to it is **harvest**; the gap is curtailed solar. Days where either inverter
  reported 0 are dropped from the fit (wedged monitor, not weather).
- Validates well on daily totals (5 of 7 days within a few %), e.g. 10-08 33.1 est vs 33.2 actual.
- **Config split:** `[Forecast]` in `web/conf/config.ini` (tracked, public repo) holds tilt/azimuth/
  kwp/fit knobs; **latitude/longitude live in `web/conf/forecast.local.ini`, which is gitignored** —
  don't move them back. `_load_config()` reads both, local wins.
- **`solarVoltage × solarCurrent` IS real PV power** — verified 2026-10-13 against the instantaneous
  energy balance on raw samples (12:02 `first`: PV 331.4 V × 5.9 A = 1955 W vs load 1501 W + 267 W
  into the battery = 1768 W, 90 %; 12:00: 2144 W PV + 922 W from battery = 3066 vs 2823 W load, 92 %).
  Don't re-litigate this; it's the battery-side reading on QPIGS that would have been the trap.
- **Open-Meteo systematically under-reads clear days here.** On 2026-10-13 it modelled 57 % mean
  cloud and 3.70 kWh/m² POA for what was actually a clear day (~4.6 kWh/m²). The fitted `factor`
  absorbs that bias, which is why it implies an impossible-looking PR of ~0.94 — the factor is a
  calibration against *this model*, not a physical performance ratio. Fine in aggregate; it just
  means day-to-day cloud errors in the model pass straight through to the forecast.
- Tried and failed: fitting tilt/azimuth from the measured hourly shape. RMSE was flat (0.037–0.045)
  from due-east to south — no signal, because the measured hourly profile is shaped by *demand*
  (empty battery in the morning takes everything, full battery curtails by afternoon), not by the
  sun. Both inverters track each other to within 0.12 kW all day, so there is no east/west split —
  one orientation, confirmed. Geometry comes from the owner, not from a fit.

## Battery, solar & heat-pump energy system

**Battery bank (DC-coupled, shared bus):** 5× **14S NMC** packs (Tesla/Panasonic 18650), each
with its own **JK BD6A24S10P** BMS (24S-capable), paralleled on the DC bus. Nominal ~511 Ah /
~26 kWh, **but a real overnight test (2026-09-21) showed only ~7 kWh took the bank ~78%→~18%
(55.4→48.0 V, i.e. 3.43 V/cell = the user's "3.4 V"), so REAL usable ≈ 10–12 kWh — roughly HALF
the nominal.** The JK **`remain_ah`/SoC readings are optimistic** (configured nominal, not true
capacity) — trust voltage + delivered energy, not BMS SoC. Cells stay balanced (~30 mV spread),
so it's capacity fade, not a fault. Live per-pack data:
`methods.battery_packs()` (InfluxDB `bms_battery-N`) + MQTT `home/bms/<battery-N>/snapshot`.

**The packs are NOT the same size** — 44p / 40p / 30p / 60p / 30p, all 14S, and not the
same cells either (Samsung 30E, Samsung ?, Panasonic PF, Panasonic ex-Tesla, LG MH1).
**Full registry
(cell types, per-pack measurements, BMS limits, what is still unverified) lives in
[`BATTERY_PACKS.md`](BATTERY_PACKS.md)** — read it before drawing conclusions about any
individual pack. The two things worth carrying here:

- **Always normalise delivered Ah by parallel count.** On raw Ah, battery-3 (25.2 Ah) looks
  half of battery-4 (54.4 Ah) and, with 268 cycles against 40, reads as worn out. It is not:
  per cell the whole bank falls in 0.84–0.96 Ah and battery-3 is 8 % under battery-2 *despite
  six times the cycle history*. It is the smallest pack, not a spent one. This file carried the
  wrong version until 2026-10-14; don't reintroduce it.
- **Cycle counts start at BMS install, so on salvaged cells they are not age.** Measured
  state of health 2026-10-14: battery-1 85 %, battery-5 84 %, battery-3 79 %, **battery-4
  71 %** — the ex-Tesla pack is the most worn in the bank at 40 cycles, against battery-3 at
  268. Those cells arrived with a car's history that nothing here records.
- **battery-4 has the tightest per-cell limits in the bank** (0.83 A both ways against
  1.25–3.33 A elsewhere) while being the largest pack — 50/50 A looks copied from a 40p pack.
  Nothing is near tripping (worst observed 0.85 A/cell, ~0.3C, and no MOSFET has opened since
  the stub was fixed) but it inverts the cascade order.
- **Real bank capacity, measured empty→full 2026-10-13/14: 32.0 kWh in** (NMC 18.9 + LFP 13.1),
  so ~28–30 kWh usable out. That retires the old "NMC ≈ 10–12 kWh, half of nominal" figure
  above — the NMC side is at 80–90 % of nominal. lfp-1 took 239.8 Ah against a 230 Ah
  nameplate, which is also what validates the BMS current readings.
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

> ## ⚠ HARDWARE CHANGED 2026-10-22 — INSTALLATION UNFINISHED
>
> **The parallel pair is gone. One new 10.2 kW Easun now runs the house, and the install is
> only half done — read this before acting on anything below about "the two inverters".**
>
> What happened: the **slave's battery busbar joint burnt open** (70 A charge current through a
> degrading bolted joint on the power board, pads charred). It reported **F83 = battery voltage
> detected different**, truthfully: the pack read 53.5 V everywhere while that unit read 40.9 V
> and then floated to its 57.9 V charge setpoint with **0 A at 250 W of PV** — the signature of a
> DC path that is open, not of a bad battery. Unplugging the parallel comm cable cleared the
> fault and freed the master, which until then had held the load in bypass because its partner
> was faulted. That unit is off the wall.
>
> **Current state:** the **new 10.2 kW Easun** (`ratedInputCurrent` 44.3 A, charge 160 A — that is
> how to tell it apart from a 5 kW, which reads 22.6 A/80 A) alone carries the house, in SBU on
> battery, charger priority **OSO (solar only)**.
>
> That charger priority was found reading **CSO (solar first, so the grid tops the battery up)**
> at 02:05 on 2026-10-24, after the owner had been rewiring. Whether his work or an earlier write
> left it there cannot be established — **`invertor_status` is purged hourly** by
> `writePerMinute`, so this measurement has no history to compare against. He asked for grid
> charging off; `PCP03` was sent at 02:12, ACKed, and QPIRI field 17 went 1 → 3, confirmed again
> in `invertor_status` a minute later. Mains charge current was 2 A throughout, so the exposure
> while it sat on CSO was negligible. **Worth re-reading this field after any hands-on session**:
> it is one of the few settings that matters and the only one with no audit trail.
>
> ⚠ **OSO does not stop this unit charging from the grid.** With field 17 confirmed at 3, at
> 02:20 on 2026-10-24 it was still pushing ~340 W into the pack at night with PV at 0 V — the
> inverter reported 2.00 A, all six BMS packs independently measured +6.6 A. And it cannot be
> turned off: `QMUCHGCR` answers **`002 010 020 030 040 050 060`**, so the lowest selectable
> utility charge current is 2 A and it was already there. There is no "off" over the protocol.
>
> **The lever that works is `PBDV` (QPIRI[22], back-to-battery), not the charger settings.**
> The unit had dropped below the 48.0 V mains-switching point during the monitoring blackout and
> then sat in mode L, because returning to battery needed **52.0 V** and a 2 A grid charge cannot
> climb there in a night — so the house ran off the grid *and* trickle-charged from it. Lowering
> the threshold to **50.0 V** (`PBDV50.0`, 2026-10-24 02:42) put it back in mode B within a
> minute: charge current 2.0 → 0.0 A, discharge 0 → 8.8 A, BMS +6.5 → −4.6 A, with the grid still
> physically connected at 240 V as the fallback. Back-to-utility stays at 48.0 V, so the safety
> net is intact and the hysteresis band is 48.0 - 50.0 V.
>
> Generalise this: when the unit is grid-bound at night, look at the **gap between
> `batteryVoltageMainsSwitchingPoint` and `batteryRedischargeVoltage`** before touching anything
> about charging. Cutting the grid with the Tuya breaker would have moved the whole house load
> onto the battery (~8 kWh by morning) to save ~2 kWh of trickle, and removed the 48 V fallback.
>
> ⚠ **It is read from `.225`, not `.223`, since 2026-10-23 14:04.** The USB-serial link on `.223`
> would not stay up (item 7), so the cable was moved to the other Pi. **The unit is still
> `second` everywhere** — Redis `invertor_2`, MQTT `home/invertor/snapshot/second`, the
> `deviceNumber` field — because the host changed and the inverter did not. `.225` therefore runs
> a new **`invertor-second.service`** (in `/etc/systemd/system/`, `invertor.py second`), and both
> `invertor-first` on `.225` and `invertor-second` on `.223` are **stopped and `disable`d**.
>
> That disable matters: `invertor-first` was still `enabled` on `.225`, came back on its own after
> a reboot, and spent three minutes writing the 10 kW's readings under `deviceNumber='first'`.
> Nothing sums to the truth after that — every consumer adds the units up, so one inverter under
> two identities doubles the PV, the load and the battery current, and it would also have poisoned
> `fit_factor`, which now derives the unit count from the data. 144 rows were deleted from
> `invertor_actual` (12:04–12:07 UTC; no `second` rows in that window, they stopped at 12:02).
> **`invertor_1` is gone** — Redis key deleted and the retained `home/invertor/snapshot/first`
> cleared, again. `tuya.service` (grid breaker) is still **stopped**, waiting on a go-ahead.
>
> **A missing unit must never be an error — it is the normal state now.** Two places assumed the
> pair and broke quietly when `first` stopped writing:
>
> * `invertor/aggregate.py` looped over `["first", "second"]` and did `df["invertor"]` unguarded.
>   The empty `first` query raised `KeyError` on the **first** iteration, so the minutely
>   `agg.sh today` died before ever aggregating `second`. `invertor_daily` then had no row for
>   today, `invertor.py`'s `select … from invertor_daily where time > now() - 24h` returned
>   nothing, Redis carried `last={}`, and the **Today block on `/invertor.html` showed `NaNkWh`
>   on all six lines** while today's bar was missing from the solar chart. Fixed 2026-10-24: a
>   unit with no rows is logged and skipped.
> * `templ/tablet.html` drew a hard-coded second card and a two-column settings table headed
>   `first (.225) / second (.223)`. Fixed the same day — units come from the data, and the
>   MASTER/SLAVE badge and the mismatch verdict only appear when there really are two.
>
> When something in a UI is blank, check this class of bug before the sensor: the pattern is
> always a hard-coded two, not a dead device.
>
> **Unfinished / next:**
> 1. **Two MPPTs — and we only see one of them. THIS IS A LIVE DATA BUG.**
>    The unit is `QMN` = `VMII-NXPW5KW9`, firmware `52.03`, protocol `PI30`, nameplate **5400 W +
>    5400 W, 18 A, 500 V per PV input**. Its **LCD cycles through two separate MPPT pages** showing
>    genuinely different operating points at the same moment (owner, 2026-10-23: *1.9 A / 275 V*
>    and *2.1 A / 350 V*). Two different voltages cannot exist on one node, so these are two
>    independent trackers.
>
>    **`QPIGS` reports only one of them.** Proven by the energy balance, which is the test that
>    needs no nameplate: charger priority is **OSO (solar only)**, so on grid every watt into the
>    battery came from PV. Measured over 20 samples, 2026-10-23 ~08:40:
>
>    ```
>    PV reported   710 W
>    into battery  942 W      -> at least 232 W of PV is not reported
>    ```
>
>    and that 232 W is a *lower bound* — it ignores conversion loss and any PV the unit sends
>    straight to the load. The owner's own display readings imply ~520 W missing at that moment,
>    i.e. **roughly 40 % of production is invisible**. So `solarCurrent`, `solarVoltage`, PV power,
>    the daily/monthly PV totals and the `forecast_solar` calibration factor are **all understated**
>    and must not be trusted until this is solved.
>
>    ✅ **SOLVED 2026-10-26 (`efac0f0`) — Modbus RTU on the RS232 port we already had.**
>    Every one of the ~45 PI30 commands swept really does NAK (`QPIGS2`, `QP2GS`, `QMPPTT`,
>    `QPVIPGS`, `QET`, `QEY/QED`, …), the PI18 envelope really is silent, and `QPIGS` really is
>    the standard 21 fields with no spare PV slot. The mistake was assuming that settled it. The
>    unit speaks **two protocols on one wire**: PI30 ASCII, and **Modbus RTU as slave 5, same
>    port, same 2400 Bd**.
>
>    `QMN` answers **`VMII-NXPW5KW9`** — the Daxtromn / PowMr VM II family. Register numbers from
>    softwarecrash/Solar2MQTT PR #25, confirmed on our own unit at night with the array dark:
>
>    | reg | field | reading |
>    |---|---|---|
>    | 4504 / 4505 | PV1 voltage (0.1 V) / power (W) | 44.7 V / 0 W |
>    | 4563 / 4564 | PV2 voltage (0.1 V) / power (W) | 44.0 V / 4 W |
>    | 4557 | heat-sink temperature | 40 °C, agrees with QPIGS |
>
>    ⚠ **Registers are little-endian**, which Modbus normally is not: `0xB901` read the usual way
>    is 47361, read swapped it is 441 = 44.1 V. ⚠ **Function 4 is rejected**; function 3 answers.
>    The 9-byte-frame theory from the forums is a red herring here — sending the CR separately
>    changes nothing, and `QET` NAKs at 6 bytes.
>
>    Interleaving was measured before being trusted: six consecutive QPIGS + Modbus pairs on the
>    one port, zero errors. `Invertor.readMppt()` is throttled to 30 s, swallows its own
>    exceptions, gives up after 20 consecutive failures and flushes the input buffer in a
>    `finally`, so PI30 polling cannot lose a cycle to it. Fields published:
>    `mppt1Voltage/Power`, `mppt2Voltage/Power`, `mpptPowerTotal`.
>
>    The reconstruction below is **left in place deliberately** so the estimate can be scored
>    against measurement. Retire it only once a few sunny days agree.
>
>    Two beliefs recorded here were wrong and are kept as a warning: that the dongle or a DC clamp
>    were the only avenues left, and that RS485 being labelled BMS closed the subject. Neither
>    mattered — the answer was a second protocol on the cable already plugged in.
>
>    **The search is now closed from the other side too, 2026-10-23 (`f024f50`).** `QPIGS_FIELDS`
>    had only 16 entries while the frame carries 21, so `refreshData` read the whole reply and
>    threw the tail away — for months, while ~45 commands were being swept from the outside for
>    exactly the number that was arriving every second. The tail is now parsed. It does **not**
>    hold tracker 2:
>
>    | field | value on this unit | what it is |
>    |---|---|---|
>    | 16 | `00010110` | status bits (see below) |
>    | 17, 18 | `00`, `00` | fan-voltage offset, EEPROM version — empty here |
>    | 19 | 1688 W against `5.2 A x 331.1 V` = 1722 W | the inverter's own PV power, **same single tracker** |
>    | 20 | `010` + CRC | status bits, frame CRC glued on |
>
>    Field 19 is published as `pvChargingPower` anyway — it is the unit's own measurement rather
>    than our product, and the 34 W gap is just the current being rounded to tenths. Field 16
>    decodes as load on / charging on / **SCC charging on / AC charging off**, which is the
>    inverter's own word for the assumption the whole reconstruction rests on: it does not charge
>    from the grid. That had only one night's observation behind it until now.
>
>    **Reconstruction, deployed 2026-10-23 (`7646cd0`).** `invertor.py` publishes
>    `solarPowerMeasured` (what the one visible tracker reports) beside `solarPowerTotal`, rebuilt
>    from the flows that *are* complete — in mode L PV shows up only as charge, in mode B the
>    array covers load plus net battery. Both are kept, because the method understates while the
>    battery is float-limited and the gap between the two is what shows it. Validated twice
>    against reality:
>
>    | | visible tracker | reconstructed | |
>    |---|---|---|---|
>    | vs. owner's LCD, both trackers | 1224 W | 2241 W | LCD total was 2201 W — **2 % apart** |
>    | at 4 kW, 2026-10-23 09:11 | 2206 W | 4117 W | **1.87×** — hidden tracker ≈ 1911 W |
>
>    That 1.87× is the independent confirmation: two trackers of nearly equal output, which is
>    exactly what two matched 2p8s strings must give. `checker.py` consumes `solarPowerTotal`
>    (`66911fd`); the charts, `methods.py` and the forecast calibration still read
>    `solarCurrent × solarVoltage` and are **still half**.
>
>    **Caution — an early reading here was wrong and the way it was wrong is instructive.** At
>    07:40 the same balance closed perfectly (PV 195 W, charge 196 W) and that was taken as proof
>    of a single tracker. It was dawn: tracker 2 had not reached its start voltage yet. A balance
>    that closes proves nothing unless it is checked when **both** sources could be running.
>
>    **Reworked 2026-10-26 (`BankMonitor`), because the battery term was wrong in both modes.**
>    The original mode-L branch rested on "the unit does not charge from grid", which the note
>    below already contradicts, and on QPIGS's charge current, which in that mode is not a
>    measurement at all: on grid with the array at 0 V it reported **exactly 2.00 A for four
>    hours** — that is `mainsMaxChargingCurrent` — while the six BMS packs measured **+6.24 A**
>    between them, split in proportion to pack capacity (1.74 A into the 135 Ah pack, 0.46 A into
>    the 70 Ah one), which random shunt offsets could not produce. So `solarPowerTotal` was
>    publishing the grid trickle as sunshine: 128 W at 05:00 on 10-26 with the array making 2 W.
>
>    Both branches now take the battery term from the shunts over MQTT (`home/bms/+/snapshot`,
>    all six packs, 30 s staleness, otherwise the mode-L branch returns the visible tracker
>    rather than guessing), and mode L subtracts the trickle, **measured** where it stands alone:
>    dark, mode L, nothing else entering the pack. Long time constant, persisted in
>    `invertor/grid_trickle.json`, seeded at 313 W @ 50.6 V from the 10-25 night. It is only a
>    first-order correction — the charger tapers as the pack fills — and it stops being needed
>    at all once `gridmeter/` is reading the real thing.
>
>    QPIGS reads low in mode B too (10-26 07:45: 25.0 A against 31.5 A on the shunts), which is
>    ~340 W of array, and is most of the owner's "string 2 sits ~400 W under the LCD". Still
>    missing: a term for the inverter's own idle draw, ~60 W by a fit over quiet mode-B nights
>    where the pack is provably the only source.
>
>    ⚠ `chargingSourcePriority` was back to **CSO** on 2026-10-26 after the outages, having been
>    set to OSO on 10-24. It makes little practical difference (see below — OSO does not stop the
>    trickle either), but it confirms this field does not stay put.
>
>    **Sizing is fine either way.** Measured over 55 533 ten-minute windows of the old pair:
>
>    | | measured peak | limit | |
>    |---|---|---|---|
>    | current per input | **16.8 A** (2026-06-28) | 18 A | never reached |
>    | string voltage | **377 V** | 500 V | 8 in series, cold-Voc safe |
>    | total PV power | **11 550 W** (2026-03-27) | 10 800 W | over on **30 of 55 533 windows = ~5 h/yr** |
>
>    The annual peak is a cold clear **February/March morning** (high Vmp), not June — June tops
>    out near 10.2 kW because the panels are hot. The battery's 150 A charge cap (~8.5 kW) binds
>    long before any of this. Two trackers also mean the strings **need not** match and shade on
>    one no longer drags the other.
>
>    **Open and worth the owner's eye:** 275 V against 350 V at the same moment on two supposedly
>    identical 2p8s strings is a 27 % difference. Same roof, same pitch, same panel count should
>    track within a few percent. Suspect shade, a string that is not fully landed (the install is
>    unfinished), or a different series count on one side.
>
> 2. **Rated power reads 200 W.** Not our bug: the QPIRI field is 4 characters and 10200 does not
>    fit, so the unit sends `0200`. Derive it from 44.3 A × 230 V ≈ 10.2 kW instead of trusting it.
> 3. **`tuya.service`** — code fixed 2026-10-23 (`c811a4e`), **service still stopped**, waiting
>    on a go-ahead to re-arm the grid breaker. It had not merely been pointed at the wrong unit:
>    the aggregate still publishes an `invertor1` key, but since the swap it holds only a config
>    block, so `data["invertor1"]["batteryVoltage"]` raised `KeyError` once a minute **inside the
>    broad `except` in `on_message`** — an exception line in the log and nothing else. A breaker
>    that logs instead of switching looks exactly like a breaker with nothing to do.
> 4. **`invertor-first` on `.225`** is stopped. Note it is not enough on its own: `invertor.py`
>    publishes its snapshot with **`retain=True`**, so the broker kept serving the dead unit's
>    last frame (`batteryVoltage 42.0`, `ratedInputCurrent 22.6`) to every new subscriber. The
>    redis TTL only hides that — it re-appears for the next 180 s each time `mqtt_bridge`
>    reconnects. Cleared with `mosquitto_pub -t home/invertor/snapshot/first -r -n`. **Any time a
>    publisher is retired, clear its retained topic too**, or it outlives the hardware.
> 5. The **burnt 5 kW** is worth repairing as a spare, but not by replacing the fuse alone — the
>    joint is the cause and the charred laminate is conductive and must be cut back.
> 6. **The `.223` CH340 dropped off the USB bus on 2026-10-23 08:32** and monitoring stopped.
>    Signature worth recognising, because it tells you software cannot fix it: `urb stopped: -32`,
>    then `USB disconnect`, then it re-enumerated as a **low-speed** device (it is a full-speed
>    part) followed by `device descriptor read/64, error -32` and `attempt power cycle`. Coming
>    back at the wrong speed means the host cannot even read the D+/D- pull-up correctly — that is
>    a contact or electrical fault in the plug or the adapter, not a driver state to reset. `lsusb`
>    showed no `1a86` at all and the port had vanished from `/sys/bus/usb/drivers/usb/`, so
>    unbind/bind had nothing to act on. **Do not reset the `1-1` hub to try harder: the Pi's
>    onboard Ethernet hangs off that same SMSC9514 hub and you will drop your own SSH.** It needs
>    a physical replug; if it returns low-speed again the adapter is failing. Note the daemon
>    handled it correctly — 30 failed reads, clean exit, systemd restart, `reset_usb.sh` reporting
>    `CH341 not found`.
> 7. **The `.223` link is hand-made and that is where the fault is.** Wires run out of the RJ45
>    and end in bare crimp sockets pushed onto the DB9 pins. Wiring, 2400 8N1:
>
>    ```
>    RJ45 1  ->  DB9 2        RJ45 2  ->  DB9 3        RJ45 8  ->  DB9 5 (GND)
>    ```
>
>    Why a loose contact there crashes **USB**, which looks like the wrong layer: RS232 swings
>    **±12 V**. When an uninsulated crimp socket shifts and touches its neighbour or the shell,
>    that ±12 V reaches somewhere it should not and takes the CH340 down with it — hence `urb
>    stopped: -32` and low-speed re-enumeration from what is really a mechanical fault at the
>    other end of the cable. **Insulate every crimp individually (heatshrink) and stop it moving**,
>    or better, fit a proper DB9 housing. Evidence it is mechanical and not a dying adapter: zero
>    read errors for the eight hours nobody touched it (2026-10-22 23:00 - 2026-10-23 07:00),
>    against 160 errors in the evening it was being worked on and 68 the next morning. Moving it
>    to a different USB port on the Pi (1-1.4 -> 1-1.5) changed nothing, which clears the socket.
>    That separating test was run on 2026-10-23 and **the cable is confirmed**, three ways:
>
>    | test | result |
>    |---|---|
>    | converter alone in the Pi, DB9 unplugged, 10 min | not one kernel message |
>    | **new** converter, DB9 plugged into the inverter | 18 min clean, then dead |
>    | same after the owner secured the joint | **2 min**, then `urb stopped: -32` again |
>    | moved to `.225`, first port tried | 14 min, then dead |
>    | moved to **another port on `.225`** (1-1.2), 2026-10-23 14:33 | **3 h 0 min, zero drops** |
>
>    So it is not the adapter: **two different CH340s died on the same hand-made cable**, and the
>    one still in the drawer had run for weeks before it was moved. Taping the crimps was not
>    enough. What is left is a proper DB9 housing with every conductor individually insulated and
>    strain relief on the body — or the inverter's own COM port, which is the remaining suspect
>    and the only one that would not be fixed by re-making the cable.
>
>    **But the last row above does not fit that story.** The same cable, in a different port on a
>    different Pi, ran 3 hours without one kernel message — six times the best previous run and
>    twelve times the median. Either the re-plug happened to seat a marginal crimp properly, or
>    the host/port is part of the mechanism after all. Do not treat the cable verdict as closed:
>    it rests on runs of 2-18 min, and one clean 3 h run is the same order of evidence. Decide it
>    the only honest way, by letting this run go overnight before touching anything. The failures
>    were never periodic, so absence over hours is the only signal available.
>
>    **That overnight run answered it, and the answer was not about the cable at all.** It ran
>    clean 14:33 - 19:16 (4 h 43 min) and ended with a *reboot of the Pi*, not a USB drop. What
>    followed was six and a half hours of silence from three separate defects, none of them
>    hardware:
>
>    * The CH340 left the bus at ~19:26. `resolveSerialPort()` found no `usb-1a86_*`, fell back
>      to **`/dev/ttyUSB0` — which on `.225` is the FTDI temperature board** — and the daemon
>      talked to a thermometer until 01:56. The port *opened*, so nothing failed and nothing
>      retried. This is the same trap the function's own docstring describes from 2026-10-20; the
>      2026-10-20 fix covered "two adapters present", not "inverter absent". The fallback is gone:
>      it now raises, so systemd restarts and the fault is visible in `systemctl status`.
>    * The process never exited, so **systemd never restarted it**. `MAX_READ_FAILS` cannot help
>      when the loop is blocked rather than failing, and the block was in `Monitor.__init__` →
>      `getGeneralStatus()`, which recursed on an unanswered QPIRI without any limit. Now bounded
>      by `QPIRI_MAX_RETRIES`, and a **SIGALRM watchdog (`WATCHDOG_SECONDS = 300`) is armed before
>      `Monitor()` is constructed** and re-armed after every parsed frame. A signal fires even
>      when the process is stuck in a read on a USB device that went away, which pyserial's own
>      timeout does not cover. Verified by test: a process blocked on an empty pipe exits in 2 s.
>    * `reset_usb.sh` passed `usbreset` a bare **`1/4`**. That tool wants `BBB/DDD` *zero-padded*;
>      given `1/4` it finds nothing and falls through to matching the argument as a **product
>      name**, so on 2026-10-23 19:26 it reset the **FT232R temperature board** while logging
>      "resetting CH341". Now `printf '%03d/%03d'`, and the ttyUSB0 fallback is removed — if no
>      1a86 device is on the bus there is nothing to reset and it says so.
>
>    Moral, and it generalises: **on this host every silent-monitoring incident so far has been
>    the daemon happily reading the wrong device, never a dead one.** Prefer failing loudly.
>
>    **2026-10-24, first night with the fixes in.** The link ran clean **02:43:51 - 09:58:48
>    (7 h 15 min)** — the longest run ever recorded, and it covered the whole night. It then
>    dropped twice in three minutes, 09:58 and 10:00, each time `urb stopped: -32` -> disconnect
>    -> re-attach, and **both recovered by themselves inside 90 s**: the watchdog fired, systemd
>    restarted, `reset_usb.sh` re-enumerated the right adapter, and Influx lost two samples
>    instead of six hours. The machinery works; the drops themselves are not fixed.
>
>    Both drops landed minutes after the owner closed the breakers and the unit went to ~80 A of
>    charge and ~3 kW of PV. Tempting, and worth testing — but **the 2026-10-23 19:26 drop
>    happened after dark with the array at 0 V**, so load is at best a trigger, not the cause.
>    What to do with it: before re-making the cable, log `batteryCurrent` against the next few
>    drops. If they cluster above ~60 A the problem is coupling into an unshielded hand-made
>    cable run next to the DC bus, and ferrites plus a proper shielded DB9 housing are the fix;
>    if they scatter, it is the crimps. Also note `.225` logged **zero under-voltage events in
>    these 8 hours**, against 24 in 3 h the day before — so the Pi's supply is not the common
>    factor either, and the PSU swap drops down the list.
> 8. One **USB-serial cable is dead** — the one taken apart to inspect it. It enumerates on USB
>    (so chip and all four USB wires are fine) but passes nothing to the DB9; suspect the solder
>    tabs or the board shorting to the shell. `invertor/serial_loopback.py` settles it in seconds.
>
> 8b. **The replacement cable bought on 2026-10-28 was a JK BMS cable, not an inverter one.**
>    Stamped JKBMS on the head, which is where this should have ended -- instead it cost an
>    evening. The signature, for next time: plugged in, the daemon opened the port and got
>    `ERROR data: <['']>`; `QPI` at 2400 with every RTS/DTR combination and a passive listen drew
>    **not one byte**, and silence rather than garbage already means nothing reaches RX at all.
>    Unpowered, only RJ45 pins **1, 2, 7 and 8** read anything against the USB shell -- 215 kOhm
>    each, and 430 kOhm pin-to-pin, i.e. twice the same path through one common node, which is
>    what an unpowered transceiver's ESD diodes look like. That pin set is the JK's RS485 port,
>    and it is *also* this inverter's BMS socket (manual: 1,8 = B, 2,7 = A), so it reads as
>    plausible right up to the point where nothing answers. The original hand-made harness went
>    back on and reads fine. **The cable is not waste** -- it is the right cable for the JK on the
>    LFP pack, which is currently read over BLE and drops often enough to show in dmesg.
>
> 9. ⚠ **The inverter output is on a single B16 and two of them are paralleled as a stopgap.**
>    The old pair had one 16 A breaker each; with one inverter left, one B16 now carries the whole
>    house and trips — see the outage note below. The owner could not get a 40 A and has put two
>    B16s in parallel for the time being, knowing it is wrong, and asked to leave it.
>    **Paralleled MCBs do not add up**: the current divides by contact and trip-element resistance,
>    not evenly, so the loaded one opens first and hands the lot to the other, which follows. The
>    pair therefore trips somewhere between 26 and 32 A, unpredictably, against a measured house
>    peak of 29.6 A. The real exposure is a short circuit, where breaking capacity is *not*
>    additive and whichever opens first takes the full fault current alone. The clean fix is one
>    breaker sized to the **cable**, not to the inverter (2.5 mm² -> B16/B20, 4 -> B25, 6 -> B32,
>    10 -> B40/B50; 29.6 A peak means B32 on 6 mm² is enough and is far easier to buy than a B40),
>    or simply keeping the two breakers but giving each its own circuit. Cross-section not yet
>    known. **Do not add load from code while it stands like this** — `checkSolarBoost` raising the
>    HP water target to 50 °C is the one place this system increases house load on its own. An
>    alert on sustained load and a boost cut-out were both offered and declined for now.
>
> House load, measured over 30 days: median 753 W, p99 4.7 kW, **max 6.8 kW**, over 5 kW for about
> 10 min/day. So a single 5 kW unit genuinely cannot carry this house — the 10 kW can, with room.

**Inverters:** 2× PIP/MPP-style units, each a **Raspberry Pi running `invertor.py`** with a USB-serial
link to its inverter, reachable **only via SSH-jump from .224** (they sit on 192.168.**1**.x, /23 with
.224). Historically **192.168.1.225 = `invertor-first` = inv1** (redis `invertor_1`) and
**192.168.1.223 = `invertor-second` = inv2** (`invertor_2`) — but since 2026-10-23 there is one
inverter, it is `second`, and it is read from **`.225`**; `.223` has no inverter on it. Do not
read the host out of the service name. Managed by systemd (`invertor-first/second.service`), config
at `/home/pi/smart.home/invertor/conf/config.ini`, logs `invertor/log/invertor_{first,second}_log`.
One-shot settings (POP/PCVV/PBFT/…) go through **`invertor/send_command.py`** — stop the daemon
first, it holds the port. Never put one of those on a timer: EEPROM wear is what the September
outages were.
They feed InfluxDB db `invertor` (`invertor_status` = config, `invertor`/`invertor_actual` = live,
`invertor_daily`/`_monthly` = aggregates); heat-pump data is in db `hp` (field `power`). Config: output
priority **SBU** since 2026-10-21 (Solar→Battery→Utility; it was **SOL** = battery last, which is
why the battery was barely cycled and the pair sat in bypass at 54 V — in SOL no voltage threshold
is consulted at all, the battery is simply last in line). **Output priority DOES propagate from
master to slave** — one `POP02` on `.223` put both units in SBU and both went from mode L to B,
unlike charge current which has to be set per unit. Switching back is `POP01`. **No automation
touches this**: the owner does not want modes flipped by battery state, and repeated writes are
exactly what wore the EEPROM. Charging
**OSO** (solar-only), input range **ALP** (Appliance), float 57.7 / bulk 57.8 / mains-switch 47 /
back-to-battery **52.0** / shutdown 45.5 V (float/bulk later raised +0.2 V to 57.9/58.0 — see the sensing-offset finding below),
**solar charge: master 80 A + slave 70 A = 150 A total, and the slave cannot be raised** — it
ignores MNCHGC over serial (ACKs and keeps 70) and the owner confirmed 2026-10-15 that its own
panel will not take 80 A either. Treat 150 A as a hard ceiling, not a setting.

**PV array: 32× 450 W = 14.4 kWp on the roof**, split as **one 2p8s array per inverter** (16 panels /
7.2 kWp each), due south, roof ~15° plus a few degrees of lift on the mounts ≈ **20°** (owner,
2026-10-13). The 8-in-series is confirmed by measurement: strings run ~335 V = 41.9 V/panel = Vmp of
a 450 Wp module. Clear-day sanity check for 50.13°N in October: noon POA ≈ 750 W/m² (75 % of STC) →
~8.6 kW peak, ~53 kWh/day — matched by the 8.33 kW / 52.3 kWh actually measured on 2026-10-13, so
numbers in that range are correct and not a metering fault. That matters for sizing decisions: the
charge-current cap, NOT the panels, is the binding limit on a good day — 150 A at ~57 V is only ~8.5 kW.
(The 9×450 W / 4 kWp figure elsewhere in this file is the *planned fence addition*, not the array total.)

**Inverter findings (2026-09-24):**
- **Parallel setup + master/slave:** the two units ARE a parallel pair (Program 28 = PAL on both,
  joined 230 V output, ~50/50 load share). Originally **Master = inv1 (`first`, .225); Slave = inv2
  (`second`, .223)** — confirmed by powering the slave off: the master alone held 229 V/50 Hz and the
  whole load. BUT the firmware doesn't expose parallel status over the protocol: **QPGS0/QPGS1 return NAK
  and QPIRI reports parallelMode = 0 (NP)** even though it's PAL — an incomplete-firmware quirk (so you
  can't read master/slave from the daemon; it's whatever was set physically).
- **MASTER/SLAVE SWAPPED 2026-10-10 (F80 localization test):** the user physically swapped the
  master/slave role of the two units; **the Pi↔physical-unit USB wiring is UNCHANGED** (each Pi still
  reads the same physical box). So now: **`.225`/`first` = the box that used to be master → now SLAVE;
  `.223`/`second` = the box that always faulted F80 as slave → now MASTER.** This is the swap-to-localize:
  **next F80 on `.223`'s log** (same physical box, now master) = fault follows the BOX → that unit's CAN
  hardware is bad → service/replace it; **next F80 on `.225`'s log** (the new slave role) = fault follows
  the slave ROLE → firmware/parallel bug, not a specific unit. Black-box QPIWS logging runs on both, so
  the next trip writes which one. (Still too early at swap time to have a verdict.)
- **Charge-current taper & the asymmetry:** `invertor.py` sets max charge current by battery voltage
  each minute (`setChargeCurrent`, config `[Charge] stages`). In parallel, only the **master's** `MNCHGC`
  takes effect; the **slave ignores its own** and the master's value doesn't propagate to it, so the slave
  sits at 70 A. The old taper (`57.0:10…`) throttled only the master below the slave → that was the "one
  inverter idle, one working, running hot" asymmetry. **Fixed: taper neutralized to `stages = 60.0:80`
  (always 80 A) on both** so the master matches the slave; the CV voltage (57.8/58.0) does the top-off.
  To actually *limit* charge current, set it on **both panels** (Program 02), not per-unit via the daemon.
  **This write-through is also the only reliable way to tell master from slave** (QPGS NAKs and QPIRI
  always says NP): after a daemon restart, read back `solarMaxChargingCurrent` — the unit that shows the
  new value IS the master. Confirmed 2026-10-12 after the physical swap: daemon wrote 80 A on both,
  `.223`/second read back **80** (master), `.225`/first stayed at **70** (slave, write ACKed but ignored),
  so the slave's panel has to be set by hand.
- **`ERROR data: <['']>` has TWO causes — check which before reaching for usbreset.** The
  adapter wedging is one (below). The other, found 2026-10-21: **the daemon was opening the
  wrong device.** `/dev/ttyUSBn` is assigned in plug order, so a temperature-sensor board
  powered from `.225`'s USB (an FTDI FT232R) came up as `ttyUSB0` and pushed the inverter's
  CH340 to `ttyUSB1`; the port opened fine and every read returned empty, for 12 h, with
  systemd restarting it 10× and `reset_usb.sh` dutifully resetting the *sensor*. Tell them
  apart with `ls -l /dev/serial/by-id/` — `usb-1a86_*` is the inverter (CH340 1a86:7523).
  **Fixed:** `resolveSerialPort()` in `invertor.py` prefers the `by-id` name when exactly one
  CH340 is present, and `reset_usb.sh` now resolves by vendor id instead of via `ttyUSB0`.
  Note the Pi stays pingable and (on `.225`) the BMS daemon keeps publishing — **BMS freshness
  is the quick test for "Pi alive vs daemon broken".**
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

**The black-box log was being deleted nightly — fixed 2026-10-21.** `RotatingFileHandler` was
constructed with `backupCount=5` but **no `maxBytes`**, which defaults to 0 = never rotate, so
the log grew without bound and a crontab line on each Pi blanked it at 01:00
(`0 1 * * * echo > .../invertor_<pos>_log`). That cron destroyed exactly the evidence the QPIWS
black box exists to collect: both Pis died abruptly at ~19:56 on 2026-10-20 and the window was
wiped at 01:00 the next morning, hours before anyone looked. Now `maxBytes=15 MB` ×5 backups
(≈3 days at ~18 MB/day) and **the cron is removed on both Pis**. Don't reintroduce a `mv`-based
rotation from cron — the daemon holds the file open, so only the handler (or `copytruncate`)
rotates correctly.

**Outage ledger (built 2026-10-21 from `last reboot` on all three hosts).** Cross-checking the
inverter Pis against `.224` separates real events from human ones, and the list is shorter than
it looked:

| date | .224 | both Pis | what it was |
|------|------|----------|-------------|
| 09-28, 09-30, 10-03, 10-09 | ✓ | ✓ | **genuine house-wide blackout** |
| 10-10 | — | ✓ | the owner's physical master/slave swap |
| 10-20 | — | ✓ | the owner switched the inverters' breaker off by accident |

So **both "Pis only" events are human**, and an earlier version of this note was wrong to infer
a fault local to the two Pis from the 10-20 event.

⚠ **"All three hosts together = a real blackout" stopped being true on 2026-10-22.** `.224` and
both Pis hang off the **inverter output**, so anything that opens that one breaker takes all
three down within seconds and looks exactly like a grid-side event. It happened on 2026-10-23
at 13:18 and was read here as a genuine blackout before the owner said otherwise: the single
remaining **B16** on the inverter output had been carrying **5149 W = 22.4 A** — 1.4x its
rating — and a B-curve MCB at 1.45x must trip within the hour, which is to the minute how long
it lasted. Before calling an outage, check the load in the last rows of `invertor_actual`.

**No genuine blackout since 10-09 — the longest clear run in the series** (they had been
arriving every 2–6 days). The F80 localisation test therefore still has no verdict: nothing has
tripped since the units were swapped on 10-10.

NB `last reboot` times on the Pis are the fake-hwclock stamp (always ~:16 past the hour, since
Pi has no RTC and the clock is restored from the last hourly save) — only `uptime -s`, read
after NTP has corrected the clock, is the real boot time. Journald's first entries of a boot
carry the same stale stamp.

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
> The rules below are threshold-based and known to contradict each other (they
> waste curtailed solar, and they can't see a bad night coming). **`ENERGY_CONTROL.md`**
> is the design note for replacing them with an objective function — read it
> before adding another threshold here.

- **The schedule writes the water target ONLY — never the HP mode** (owner, 2026-10-19).
  The pump runs its own mute/smart/strong logic; solar boost is the only place allowed to
  override it, and today it doesn't need to. `__setHpMode` is kept but deliberately unused.
  Until 2026-10-19 every target change also wrote a mode, which fought the pump for no gain.
- **Night / day-quiet / day-full schedule** (`checkHeatingSchedule`): priority is **charging the
  battery**, so the HP runs gentle by default and only ramps up when the battery is genuinely charging:
  - `night` (≥21:00 or <07:00) → **32 °C**.
  - `day_quiet` (daytime, battery **not charging** — no real sun yet / overcast) → **32 °C**.
    Priority is charging: while the battery isn't charging we keep the low night target so the HP
    doesn't ramp up and drain the pack off-solar (a cold dark morning stays gentle until the sun
    catches up). It raises to the day target only once the battery is genuinely charging (`day_full`).
  - `day_full` (daytime, SoC ≥ 80% **and** battery charge current ≥ `DAY_HP_CHARGE_MIN_A` **and** not
    discharging) → **37 °C**.
  The charge/discharge gate is on the **battery charge current** (`batteryCurrent` summed over both
  inverters), NOT raw PV watts — "the sun is up" isn't enough, the pack has to actually be gaining.
  Hysteresis (hold `day_full` to SoC-15 / discharge ≤ `DAY_HP_DISCHARGE_MAX_A`) + a dwell throttle
  (`HEATING_SCHED_INTERVAL`, 300 s) stop clouds from flapping the profile; the evening/morning night
  flip is never throttled. Tunables: `NIGHT_HP_*` / `DAY_HP_*` / `HEATING_SCHED_INTERVAL`. State in
  Redis `heating_sched_mode` (`night`/`morning`/`day_quiet`/`day_full`) + `heating_sched_ts`.
- **Bathroom morning slot** (added 2026-10-19): a fourth schedule mode. Between 04:45 and
  07:00 (`MORNING_SLOT_*`) the profile is `morning` → **37 °C** (target only), and
  `__forceBathroomLoop` holds the bathroom port (sensor 10246875) open regardless of the
  room's own vote — the bathroom sits above target all night, so the thermostat would never
  open it, and the goal is a **warm floor from 05:00**, not an air temperature. Both halves
  are required: opening the port on the night target circulates 33 °C water and warms
  nothing. The lever if the floor isn't warm enough by 05:00 is `MORNING_SLOT_START_MIN` —
  start earlier; the pump's own mode logic is not ours to turn up. Capped by `MORNING_MAX_ROOM_C` (28 °C). **Fails open** (falls back to the
  thermostat) — deliberately the opposite of the garage gate below. State in Redis
  `morning_slot_state`.
- **Garage gate** (`__gateGarage`, added 2026-10-19): the garage loop may only open when
  `solar_boost_active ∧ tank ≥ GARAGE_TANK_MIN_C` (55 °C, DPS 108) — the buffer is the first
  place surplus should go, and the garage is last in the queue behind uninsulated doors.
  **The tank bar has hysteresis** (added 2026-10-26): open at 55 °C, hold open down to
  `GARAGE_TANK_OFF_C` 50 °C. With one threshold the gate shut itself minutes after opening —
  13:02:10 open at 55.0, 13:07:34 blocked at 54.0, a degree the garage loop had drawn itself.
  50 is twelve degrees above the buffer's working minimum so the house loops never notice.
  The surplus half stays immediate: boost off ⇒ garage shut, whatever the buffer holds. The
  latch is dropped whenever the garage stops asking for heat, or it would admit the next
  request at the lower bar.
  **Fails closed in every path** (unreadable tank, Redis error, bug → garage shut), including
  the call site: a wrong "open" costs ~11 kWh of grid heat a night. State in Redis
  `garage_gate_state`.
- **Solar boost** (`checkSolarBoost`): layers on top — bumps the water target to 50 °C when there
  is surplus, and **releases the moment the battery starts discharging** (> 1 A) — charging has
  priority. **Two ways in, either suffices** (both still need daylight and a pack that is not
  already draining):
  - **SOC path** — SoC ≥ `SOLAR_BOOST_SOC_MIN` (82 %, coulomb) **and** charging ≥
    `SOLAR_BOOST_CHARGE_MIN_A` (15 A). The pack is nearly full, so the 50 °C TC won't drain it.
  - **Charge-cap path** (added 2026-10-26) — charge current ≥ 90 % of the inverter's
    `solarMaxChargingCurrent` on **2 of the last 4 checks** (`solar_boost_cap_window` in Redis).
    Consecutive was the first attempt and it was useless: the check samples an instantaneous
    current every 10 min and on a part-cloudy day it bounces (147, 58, 154, 38, 32, 106, 159, 68,
    113, 117, 113, 152, 162 A against a 160 A cap over 10:25-12:25 on 2026-10-26) — clipped much
    of the time, never twice running until the SOC gate had opened anyway. Then the MPPT is throttling to the limit by
    definition and the extra array output is being thrown away, whatever the SOC is. **The pair
    never needed this**: 150 A across two units was the whole array, so the cap and a full pack
    arrived together. One 10 kW unit behind the same 14.4 kWp hits the cap far earlier — on
    2026-10-26 it sat at 154 A of 160 for three hours **from 55 % SOC** with the boost held off on
    the SOC gate alone. A boost engaged this way records `solar_boost_reason = cap` in Redis and is
    **exempt from both SOC release tests and from the 30-min dwell** — it starts below the 85 %
    release line and usually below the 58 % hard floor on purpose, so either would throw it
    straight back out and it would re-engage ten minutes later, flapping the water target. What
    ends a cap-engaged boost is the surplus going away: the deep-drain test (> 20 A out for two
    checks), which it reaches without waiting out the dwell. On release it falls back to the schedule's current base (32 night / 37 day),
  not a stale snapshot. Skips the schedule while boost is active so they don't fight. (Old SoC-only
  engage + 3-miss hold is gone — it used to drain the pack for ~30 min after a false engage.)
- HP water target = PG1[4] via `__setHeatingTarget` (write-on-change; also syncs the
  `heatpump_status_heating_target_water_temp` Redis cache the UI reads). `heatpump_setMode`
  ("smart"/"mute"/"strong") exists for the **UI**, not the scheduler — see above.
  Note `heatpump_status.targetTemp` reads that cache, not live PG1 — it can
  lag until a write or an HP-page load resyncs it.
- **PG1[4] targets the RETURN water, not the flow.** The pump's app (Temperature Setting)
  holds two more parameters that explain the offset everyone trips over: *"Return water &
  target DHW water temp difference" = 5 °C* → the flow runs 5 °C above the return target, so
  32 gives ~37 °C into the floor and 50 gives 55+; and *"Return difference for heating &
  cooling" = 2 °C* = the restart hysteresis on the return. Both are set by hand in the app;
  nothing here writes them. The 5 °C is adjustable 2–18, i.e. a second knob on floor
  temperature that doesn't raise the buffer.
- **Flow temperature before the manifold** is measured and recorded: a 100 kΩ NTC on the
  manifold board (`manifold.switch/thermistor.h`) rides along with its 20 s ping,
  `GET /ping?t=&te=` → `server_fastapi.py` → Redis **`heating_watter`** (two t's — the key
  really is spelled that way). `state_recorder.py` archives it as `control_state.water_manifold_c`
  (since 2026-10-19). **Only valid while the circulation pump runs** — the NTC is on the pipe
  under the insulation, so with the pump off it reads standing water that decays over hours
  (τ ≈ 2–5 h), not a live flow temperature. Join on `heating_state` (= the pump) in the same
  measurement and drop the rest. The old InfluxDB measurement `heating_water` is the dead predecessor —
  its writer is not in this repo and it stopped 2026-06-13. Note the flashed manifold firmware
  is **newer than the committed `.ino`**, which never sends `te`.

## Gotchas
- **No docker-compose**; deploy is the `web/Makefile` `docker run` with a live bind mount.
- Several `crond/cron` and `*.service` files hardcode `/home/pi/smart.home/...` (Pi4 paths) and
  a few have typos — **verify a unit before trusting/enabling it.**
- The heating decision in `checker.py` only acts when a room's `heating_direction == "heating"`;
  config `hysteresis` exists but isn't applied. The daemon is hardened so a hung manifold
  (`192.168.0.5`) no longer blocks the heating relay (`192.168.0.6`).
- ⚠ **Never curl the manifold (`192.168.0.5`) with an arbitrary path.** The firmware reads
  characters 5–13 of the request line as the 9-port relay word (`'0'` = closed, anything else
  = open), so `GET /temperature` parses as `"temperatu"` and **opens all nine valves**. Worse,
  `changeManifoldStatus` writes only on change, so Redis still says `000000000` and the daemon
  never corrects it. Recover with `curl http://192.168.0.5/000000000`. Read the water
  temperature from Redis `heating_watter`, never from the device.
- Repo is public — do not commit secrets (Tuya keys, tokens, htpasswd, certs).
