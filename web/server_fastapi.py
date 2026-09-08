"""FastAPI port of server.py.

Sync handler bodies run in uvicorn's thread pool, so a slow tinytuya
call only blocks the worker that owns that request — not the whole
event loop. WebSocket dispatches `methods.X()` (also sync) through
`run_in_threadpool` for the same reason.

Production launch (production stack uses gunicorn with uvicorn workers):
    gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:8000 server_fastapi:app
"""

import json
import logging
import os
import pickle
import re
import time
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd
import paho.mqtt.client as mqtt_client
import requests
import tinytuya
from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

import methods
import utils
from config import conf


def _make_mqtt():
    """Long-lived MQTT publisher per worker. loop_start runs the network
    thread in the background, so publish() returns instantly even when
    the broker briefly hiccups (paho queues + reconnects). Each gunicorn
    worker gets its own connection — fine, mosquitto handles many."""
    c = mqtt_client.Client("smart-home-web-%d" % os.getpid())
    c.reconnect_delay_set(min_delay=1, max_delay=30)
    try:
        host = conf.Mqtt.host
        port = conf.Mqtt.port
    except AttributeError:
        host, port = "127.0.0.1", 1883
    try:
        c.connect(host, port, keepalive=60)
    except Exception as e:
        logging.warning("MQTT initial connect failed: %s", e)
    c.loop_start()
    return c


_mqtt = _make_mqtt()


log = logging.getLogger('web')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templ"))

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("X-Real-IP")
        or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )


def _ctx(request: Request, **extra) -> dict:
    """Standard template context: includes the FastAPI request and the same
    data dict shape the old Tornado handlers passed in."""
    data = {"port": conf.Web.Port, "page": request.url.path}
    data.update(extra)
    return {"request": request, "data": data}


# ---- Page handlers ------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", _ctx(request))


@app.get("/camera.html", response_class=HTMLResponse)
def camera(request: Request):
    return templates.TemplateResponse("camera.html", _ctx(request))


@app.get("/alarm.html", response_class=HTMLResponse)
def alarm(request: Request):
    return templates.TemplateResponse("alarm.html", _ctx(request))


@app.get("/solar_chart.html", response_class=HTMLResponse)
def solar_chart(request: Request):
    return templates.TemplateResponse("solar_chart.html", _ctx(request))


@app.get("/heat_pump.html", response_class=HTMLResponse)
def heat_pump(request: Request):
    return templates.TemplateResponse("heat_pump.html", _ctx(request))


@app.get("/heat_pump_chart.html", response_class=HTMLResponse)
def heat_pump_chart(request: Request):
    return templates.TemplateResponse("heat_pump_chart.html", _ctx(request))


@app.get("/heat_pump_settings.html", response_class=HTMLResponse)
def heat_pump_settings(request: Request):
    return templates.TemplateResponse("heat_pump_settings.html", _ctx(request))


@app.get("/heating_chart.html", response_class=HTMLResponse)
def heating_chart(request: Request):
    return templates.TemplateResponse("heating_chart.html", _ctx(request))


@app.get("/humidity_chart.html", response_class=HTMLResponse)
def humidity_chart(request: Request):
    return templates.TemplateResponse("humidity_chart.html", _ctx(request))


@app.get("/pressure_chart.html", response_class=HTMLResponse)
def pressure_chart(request: Request):
    return templates.TemplateResponse("pressure_chart.html", _ctx(request))


@app.get("/invertor.html", response_class=HTMLResponse)
def invertor(request: Request):
    return templates.TemplateResponse("invertor.html", _ctx(request))


@app.get("/invertor_setting.html", response_class=HTMLResponse)
def invertor_setting(request: Request):
    return templates.TemplateResponse("invertor_setting.html", _ctx(request))


@app.get("/battery.html", response_class=HTMLResponse)
def battery(request: Request):
    """Overview of every bms.monitor module — one card per pack with
    its latest snapshot from InfluxDB. New packs show up automatically
    as soon as their first POST lands in measurement bms_<pack_id>."""
    influx = conf.Influx.getClient()

    # Discover bms_* measurements dynamically; new packs appear without
    # any code change once they POST their first row.
    res = influx.query("SHOW MEASUREMENTS")
    packs = []
    for row in res.get_points():
        name = row.get("name", "")
        if name.startswith("bms_"):
            packs.append(name)
    packs.sort()

    overview = []
    for measurement in packs:
        # Last row, all columns.
        q = f'SELECT * FROM "{measurement}" ORDER BY time DESC LIMIT 1'
        try:
            r = influx.query(q)
            point = next(iter(r.get_points()), None)
        except Exception as e:
            log.warning("battery query failed for %s: %s", measurement, e)
            point = None
        if not point:
            continue

        # Render-friendly view-model. cells_mv is a list per cell so
        # the template can sparkline them.
        cells = []
        cells_res_mohm = []
        for i in range(1, 25):
            v = point.get(f"cell_{i:02d}_mv")
            if v is None:
                break
            cells.append(int(v))
            r = point.get(f"cell_{i:02d}_res_mohm")
            cells_res_mohm.append(float(r) if r is not None else None)

        ts = point.get("time")
        age_s = None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_s = int((datetime.now(dt.tzinfo) - dt).total_seconds())
        except Exception:
            pass

        total_v = (point.get("total_mv") or 0) / 1000.0
        current_a = (point.get("current_ma") or 0) / 1000.0
        overview.append({
            "pack_id":      measurement[len("bms_"):],
            "ts":           ts,
            "age_s":        age_s,
            "cell_count":   point.get("cell_count"),
            "total_v":      total_v,
            "soc":          point.get("soc"),
            "current_a":    current_a,
            "power_w":      total_v * current_a,
            "cycle_count":  point.get("cycle_count"),
            "remain_ah":    (point.get("remain_mah") or 0) / 1000.0,
            "our_cycles":   point.get("our_cycles"),
            "our_dch_ah":   point.get("our_dch_ah"),
            "our_ch_ah":    point.get("our_ch_ah"),
            "cell_min_mv":  point.get("cell_min_mv"),
            "cell_max_mv":  point.get("cell_max_mv"),
            "cell_avg_mv":  point.get("cell_avg_mv"),
            "cell_delta_mv": point.get("cell_delta_mv"),
            "cells":        cells,
            "cells_res_mohm": cells_res_mohm,
            "temp_1_c":     point.get("temp_1_c"),
            "temp_2_c":     point.get("temp_2_c"),
            "temp_3_c":     point.get("temp_3_c"),
            "temp_4_c":     point.get("temp_4_c"),
            "ble_rssi_dbm": point.get("ble_rssi_dbm"),
            "wifi_rssi":    point.get("wifi_rssi"),
            "uptime_s":     point.get("uptime_s"),
            "source":       point.get("source") or point.get("client_ip"),
        })

    return templates.TemplateResponse(
        "battery.html",
        _ctx(request, packs=overview),
    )


@app.get("/radar.html", response_class=HTMLResponse)
def radar(request: Request):
    return templates.TemplateResponse("radar.html", _ctx(request))


@app.get("/tablet.html", response_class=HTMLResponse)
def tablet(request: Request):
    """Wall-mounted tablet dashboard (Lenovo P11, landscape). Standalone
    page — does not use the legacy _head/_menu chrome. Rooms are rendered
    server-side (name + current setpoint); live values, solar/battery and
    heat-pump control all run over the same /websocket JSON-RPC the other
    pages use (heating_SensorRefresh, invertor_load, heatpump_status)."""
    db = conf.db.conn
    rooms = []
    for id_, name in conf.Heating.items.items():
        try:
            room = pickle.loads(db.get("heating_" + id_))
        except Exception:
            room = {}
        rooms.append({
            "id": id_,
            "name": name,
            "temperature": "%.1f" % room.get("temperature", .0),
            "external": id_ in conf.HeatingSensors.external,
        })
    return templates.TemplateResponse("tablet.html", _ctx(request, rooms=rooms))


@app.get("/temperature.html", response_class=HTMLResponse)
def temperature(request: Request):
    return templates.TemplateResponse("temperature.html", _ctx(request))


@app.get("/windows.html", response_class=HTMLResponse)
def windows(request: Request):
    rooms: dict = {}
    for short_id, cfg in conf.Blinds.items.items():
        rooms.setdefault(cfg.get("room", "Other"), []).append({
            "id": short_id,
            "name": cfg["name"],
        })
    return templates.TemplateResponse("windows.html", _ctx(request, rooms=rooms))


@app.get("/light.html", response_class=HTMLResponse)
def light(request: Request):
    # Switch state is published into Redis by lights_poller.service.
    # The page render does cache reads only, so a dead device (Solar
    # in with no PSU, etc.) no longer adds 5 s per box to load time.
    lights, devices = [], []
    db = conf.db.conn
    now = int(time.time())

    def _read(id_):
        raw = db.get("light_state_" + id_)
        if not raw:
            return None, None
        try:
            d = pickle.loads(raw)
            return d.get("value"), now - d.get("ts", 0)
        except Exception:
            return None, None

    for id_, values in conf.Lights.items.items():
        value, _ = _read(id_)
        lights.append({
            "id": id_,
            "name": values["name"],
            "type": "relay",
            "value": value,
        })

    # Show ONLY plain on/off switches here. Rolety have their own
    # /windows.html, the camera and the heat-pump unit have their own
    # dashboards — listing all of them on /light.html was the source
    # of the "neaktuálni" feel.
    SWITCH_PKEYS = {"keyjup78v54myhan", "keyuh3jxk9wu8ruj"}
    for _id, device in conf.Tuya.devices.items():
        if not device.get("name") or not device.get("ip"):
            continue
        if device.get("productKey") not in SWITCH_PKEYS:
            continue
        value, _ = _read(device["id"])
        devices.append({
            "id": device["id"],
            "type": "tuya",
            "name": device["name"],
            "value": value,
        })

    return templates.TemplateResponse(
        "light.html",
        _ctx(request, lights=lights, devices=devices),
    )


@app.get("/heating.html", response_class=HTMLResponse)
def heating(request: Request):
    db = conf.db.conn
    rooms = []
    for id_, name in conf.Heating.items.items():
        try:
            room = pickle.loads(db.get("heating_" + id_))
        except Exception:
            room = {}
        rooms.append({
            "id": id_,
            "name": name,
            "temperature": "%.1f" % room.get("temperature", .0),
            "actualTemperature": .0,
            "humidity": .0,
            "external": id_ in conf.HeatingSensors.external,
        })
    return templates.TemplateResponse(
        "heating.html",
        _ctx(request, ids=list(conf.Heating.items.keys()), rooms=rooms),
    )


@app.get("/heating_setting.html", response_class=HTMLResponse)
def heating_setting(request: Request, id: str = ""):
    db = conf.db.conn
    sensor_id = conf.HeatingSensors.names.get(id)
    actual_humidity = "-"
    actual_temperature = 0.0
    req_temperature = float(conf.Heating.minimalTemperature)

    raw = db.get("temp_sensor_%s" % sensor_id) if sensor_id else None
    if raw:
        sensor = pickle.loads(raw)
        actual_humidity = sensor.get("humidity")
        actual_temperature = sensor.get("temperature")

    room_raw = db.get("heating_" + id) if id else None
    if room_raw is not None:
        room = pickle.loads(room_raw)
        req_temperature = room.get("temperature", req_temperature)

    return templates.TemplateResponse(
        "heating_setting.html",
        _ctx(
            request,
            id=id,
            roomName=conf.Heating.items.get(id, "unknown"),
            reqTemperature="%.1f" % req_temperature,
            actualTemperature="%.1f" % actual_temperature,
            actualHumidity=actual_humidity,
        ),
    )


@app.get("/heating_log.html", response_class=HTMLResponse)
def heating_log(request: Request, date: str = ""):
    db = conf.db.conn
    now = datetime.now()
    month = now.strftime("%Y-%m")
    items = pickle.loads(db.get("heating_time_%s" % month))

    out = []
    suma = timedelta(0)
    for t1, t2 in zip(*[iter(items)] * 2):
        if t1["date"][:10] == now.strftime("%Y-%m-%d"):
            div = (datetime.strptime(t2["date"], "%Y-%m-%d %H:%M:%S")
                   - datetime.strptime(t1["date"], "%Y-%m-%d %H:%M:%S"))
            out.append({"len": div, "start": t1["date"], "end": t2["date"]})
            suma += div
    out.reverse()

    return templates.TemplateResponse(
        "heating_log.html",
        _ctx(
            request,
            items=out,
            suma=utils.strfdelta(suma, "{hours}h {minutes}m {seconds}s"),
        ),
    )


# ---- Lightweight POST-from-sensors endpoints ---------------------------

@app.get("/ping", response_class=PlainTextResponse)
def ping(request: Request, t: str = "", te: str = ""):
    conf.db.conn.set("heating_watter", te)
    log.info("Ping from IP:<%s> time:%s temperature:%s",
             _client_ip(request), t, te)
    return ""


@app.get("/sensor", response_class=PlainTextResponse)
def sensor(temperature: str = "", humidity: str = "", id: str = ""):
    log.info("Temp:%s hum:%s id:%s", temperature, humidity, id)
    return ""


@app.get("/stove", response_class=PlainTextResponse)
def stove(t1: str = "", t2: str = "", v: str = ""):
    log.info("Temp 1:%s temp 2:%s v:%s", t1, t2, v)
    return ""


@app.get("/sensorTemp")
def sensor_temp(request: Request, id: str = "", t: str = "", v: float = 0,
                h: float = 0, p: float = 0, r: str = "", s: str = ""):
    infx = conf.Influx.getDfClient()

    sensor_id = id
    temperature = float(t)
    if v:
        temperature = temperature / 10

    data = {
        "ip": _client_ip(request),
        "sensorId": int(sensor_id),
        "temperature": temperature,
        "humidity": float(h),
        "pressure": float(p),
        # Unix epoch seconds — the UI uses this to render "Xm ago" in
        # the room cell so stale readings are visually obvious.
        "updated_ts": int(time.time()),
    }
    # Battery / ESP-side RSSI — anything weaker than ~-75 dBm explains
    # missed publishes and the WiFi-connect restarts we see in the log.
    if s:
        try:
            data["rssi"] = int(s)
        except ValueError:
            pass
    # `r` shows up only on the first publish after the sensor booted —
    # ESP.getResetReason() with spaces replaced by underscores. A surprise
    # WDT or Hardware_Watchdog here points at firmware lockups; a
    # Power_on lines up with the breaker or wall wart.
    if r:
        log.info("Sensor boot: id=%s reason=%s rssi=%s", sensor_id, r, s or "?")
    # Publish to MQTT — smart-home-bridge re-encodes for the legacy
    # Redis key temp_sensor_<id> that checker.py / methods still read.
    _mqtt.publish("home/temp/sensor/%s" % sensor_id,
                  json.dumps(data), qos=0, retain=True)

    # ns-precision UTC index. pandas 2.x' Timestamp.now() defaults to us,
    # which InfluxDB's DataFrameClient writes verbatim as nanoseconds and
    # so every row lands at ~1970-01-21. utcnow() gives us a true ns
    # Timestamp; tz_localize(None) strips the UTC tag the writer expects.
    dt = pd.Timestamp.utcnow().tz_localize(None)
    df = pd.DataFrame(data, index=pd.DatetimeIndex([dt]))
    infx.write_points(df, "sensor", time_precision=None)

    log.info("Sensor: %s", data)
    return JSONResponse(data)


@app.post("/bms")
async def bms_post(request: Request):
    """Per-pack BMS readings from the bms.monitor ESP modules. One row
    per POST goes into measurement bms_<pack_id> in the 'invertor'
    Influx DB; per-cell millivolts live as cell_01_mv .. cell_24_mv so
    each cell is independently queryable in Grafana."""
    try:
        body = await request.json()
    except Exception as e:
        log.warning("BMS bad json: %s", e)
        return JSONResponse({"error": "bad json"}, status_code=400)

    pack_id = str(body.get("pack_id") or "unknown")
    measurement = "bms_" + pack_id

    raw_recent = body.pop("raw_recent", None)
    if raw_recent:
        # Debug capture from bms.monitor's DEBUG_HEX_DUMP — log it but
        # don't try to shove a 2 KB hex string into InfluxDB.
        log.info("BMS raw_recent pack=%s len=%d %s",
                 body.get("pack_id"), len(raw_recent), raw_recent)

    # Whitelist — Influx only stores things that either change and are
    # not derivable from another column, or are useful metadata for
    # queries. Curated by hand rather than "log everything then
    # ignore" so the schema stays readable in Grafana.
    keep_scalars = {
        "total_mv", "current_ma", "soc", "remain_mah", "cycle_count",
        "power_w",
        "charge_mos", "discharge_mos", "balancing",
        "ble_rssi_dbm", "source",
        # Our own lifetime counters — survive JK factory reset (which
        # zeroes cycle_count) so we get a real long-term view. Fed by
        # the Pi daemon integrating current in real time.
        "our_cycles", "our_dch_ah", "our_ch_ah",
    }
    flat = {}
    for k, v in body.items():
        if k == "pack_id":
            continue
        if k == "cells_mv" and isinstance(v, list):
            for i, mv in enumerate(v):
                flat[f"cell_{i+1:02d}_mv"] = int(mv)
            continue
        if k == "cells_res_r10" and isinstance(v, list):
            # mΩ × 10 on the wire — store as mΩ float so the dashboard
            # and grafana can render 17.3 mΩ without a scaling factor.
            for i, r in enumerate(v):
                flat[f"cell_{i+1:02d}_res_mohm"] = float(r) / 10.0
            continue
        if k == "temps_dC" and isinstance(v, list):
            for i, t in enumerate(v):
                # decicelsius on the wire — store as °C float. Drop
                # SoftwareSerial-shifted nonsense outside the plausible
                # range so the dashboard doesn't spike at 1700 °C.
                c = float(t) / 10.0
                if -20.0 <= c <= 100.0:
                    flat[f"temp_{i+1}_c"] = c
            continue
        if k not in keep_scalars:
            continue  # cell_count/layout/valid/bms_age_ms/min/max/avg — derivable or static
        if isinstance(v, bool):
            flat[k] = int(v)
        elif isinstance(v, (int, float, str)):
            flat[k] = v
    flat["pack_id"] = pack_id

    dt = pd.Timestamp.utcnow().tz_localize(None)
    df = pd.DataFrame(flat, index=pd.DatetimeIndex([dt]))
    try:
        conf.Influx.getDfClient().write_points(df, measurement, time_precision=None)
    except Exception as e:
        log.warning("BMS influx write failed: %s", e)
        return JSONResponse({"error": "influx write failed"}, status_code=500)

    log.info("BMS pack=%s cells=%s total=%smV soc=%s",
             pack_id, body.get("cell_count"),
             body.get("total_mv"), body.get("soc"))
    return JSONResponse({"ok": True, "measurement": measurement})


@app.get("/sensorTempList")
def sensor_temp_list():
    db = conf.db.conn
    out = {}
    for item in db.keys("temp_sensor_*"):
        out[utils.toStr(item)] = pickle.loads(db.get(item))
    return JSONResponse(out)


@app.get("/roomsList")
def rooms_list():
    return JSONResponse(conf.Heating.items)


# ---- Radar (weather + aircraft) proxy ---------------------------------
#
# Front-end shell at /radar.html hits the three endpoints below so the
# browser never talks to adsb.fi / opendata.chmi.cz / ip-api directly:
#   * keeps the outside URLs off the page (rate limits, ToS)
#   * lets us cache in-process so 4 workers ~= 1 upstream request
#   * avoids CORS entirely
# Each gunicorn worker keeps its own tiny cache — good enough. All three
# upstream calls are sync `requests`, which is fine because handler bodies
# run in uvicorn's threadpool (see the module docstring).

CHMI_MAXZ_LISTING = "https://opendata.chmi.cz/meteorology/weather/radar/composite/maxz/png_masked/"
CHMI_MAXZ_BASE    = CHMI_MAXZ_LISTING  # PNGs live directly under it
CHMI_MAXZ_BBOX    = {  # pacz2gmaps3.z_max3d fixed footprint (WGS84)
    "south": 48.10000, "west": 11.26670,
    "north": 52.16669, "east": 20.76666,
}
CHMI_FRAMES_TTL   = 30.0
ADSB_TTL          = 4.0
LOCATION_TTL      = 24 * 3600.0
RAINVIEWER_TTL    = 60.0
CHMI_ALERTS_TTL   = 300.0
CHMI_ALERTS_LIST  = "https://opendata.chmi.cz/meteorology/weather/alerts/cap/"

_radar_cache: dict = {}


def _cache_get(key):
    hit = _radar_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_put(key, value, ttl):
    _radar_cache[key] = (time.time() + ttl, value)


@app.get("/api/radar/location")
def radar_location():
    """Home coordinates for centering the map. Env RADAR_HOME_LAT/LON
    overrides ip-api — set it when the server is not at home (VPS, etc.)."""
    env_lat = os.environ.get("RADAR_HOME_LAT")
    env_lon = os.environ.get("RADAR_HOME_LON")
    if env_lat and env_lon:
        try:
            return {"lat": float(env_lat), "lon": float(env_lon), "source": "env"}
        except ValueError:
            pass

    hit = _cache_get("location")
    if hit is not None:
        return hit

    try:
        r = requests.get("http://ip-api.com/json/", timeout=3.0,
                         params={"fields": "status,lat,lon,city,country"})
        j = r.json()
        if j.get("status") == "success":
            payload = {"lat": j["lat"], "lon": j["lon"],
                       "city": j.get("city"), "country": j.get("country"),
                       "source": "ip-api"}
            _cache_put("location", payload, LOCATION_TTL)
            return payload
    except Exception as e:
        log.warning("ip-api lookup failed: %s", e)

    # Fallback: rough center of Czechia so the map at least renders.
    return {"lat": 49.8, "lon": 15.5, "source": "fallback"}


_CHMI_FILE_RE = re.compile(
    r'href="(pacz2gmaps3\.z_max3d\.(\d{8})\.(\d{4})\.0\.png)"',
    re.IGNORECASE,
)


@app.get("/api/radar/chmi/frames")
def radar_chmi_frames(count: int = Query(6, ge=1, le=24)):
    """Last N ČHMÚ maxz composite frames + fixed bbox for imageOverlay.
    Scrapes the directory listing (updated every 5 min, ~2 kB) and caches
    for CHMI_FRAMES_TTL. `ts` is ISO-8601 UTC so JS can format it locally."""
    cache_key = ("chmi", count)
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit

    try:
        r = requests.get(CHMI_MAXZ_LISTING, timeout=4.0)
        r.raise_for_status()
        matches = _CHMI_FILE_RE.findall(r.text)
    except Exception as e:
        log.warning("CHMI listing fetch failed: %s", e)
        return JSONResponse({"error": "upstream fetch failed"}, status_code=502)

    seen = []
    for fname, date_s, time_s in matches:
        try:
            dt = datetime.strptime(date_s + time_s, "%Y%m%d%H%M").replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
        seen.append((dt, fname))
    seen.sort(key=lambda t: t[0])
    tail = seen[-count:]

    payload = {
        "bbox": CHMI_MAXZ_BBOX,
        "frames": [{"url": CHMI_MAXZ_BASE + fname,
                    "ts":  dt.isoformat().replace("+00:00", "Z")}
                   for dt, fname in tail],
    }
    _cache_put(cache_key, payload, CHMI_FRAMES_TTL)
    return payload


@app.get("/api/radar/aircraft")
def radar_aircraft(
    lat: float = Query(...),
    lon: float = Query(...),
    dist_nm: int = Query(50, ge=1, le=250),
):
    """Live aircraft near (lat,lon) from adsb.fi. Public, no key, personal
    use only per their ToS — we don't republish elsewhere."""
    # Round to keep the cache key stable across tiny mouse jitters on the
    # map — same tile ≈ same request. adsb.fi resolution is way coarser
    # than 0.01°.
    key = ("adsb", round(lat, 2), round(lon, 2), dist_nm)
    hit = _cache_get(key)
    if hit is not None:
        return hit

    url = f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{dist_nm}"
    try:
        r = requests.get(url, timeout=4.0,
                         headers={"User-Agent": "smart-home/radar (personal)"})
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        log.warning("adsb.fi fetch failed: %s", e)
        return JSONResponse({"error": "upstream fetch failed"}, status_code=502)

    # Trim to fields the map actually uses — keeps the response small
    # even when 60+ planes are in-range.
    out = []
    for a in j.get("ac", []) or []:
        try:
            plane_lat = float(a.get("lat"))
            plane_lon = float(a.get("lon"))
        except (TypeError, ValueError):
            continue
        out.append({
            "hex":      a.get("hex"),
            "flight":   (a.get("flight") or "").strip() or None,
            "lat":      plane_lat,
            "lon":      plane_lon,
            "alt_ft":   a.get("alt_baro") if isinstance(a.get("alt_baro"), int) else None,
            "spd_kt":   a.get("gs"),
            "track":    a.get("track"),
            "type":     a.get("t"),
            "reg":      a.get("r"),
            "sqk":      a.get("squawk"),
        })
    payload = {"count": len(out), "aircraft": out,
               "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    _cache_put(key, payload, ADSB_TTL)
    return payload


@app.get("/api/radar/rainviewer")
def radar_rainviewer():
    """Public RainViewer weather-maps index. Client uses this to build
    tile URLs (host + path + size + z + x + y + color + smooth_snow.png)
    and to know how many past frames it can animate."""
    hit = _cache_get("rainviewer")
    if hit is not None:
        return hit

    try:
        r = requests.get("https://api.rainviewer.com/public/weather-maps.json",
                         timeout=4.0)
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        log.warning("RainViewer fetch failed: %s", e)
        return JSONResponse({"error": "upstream fetch failed"}, status_code=502)

    _cache_put("rainviewer", j, RAINVIEWER_TTL)
    return j


_CAP_ROW_RE = re.compile(
    r'<a href="(alert_cap_(\d+)_\d+\.xml)">.*?</a>\s*(\d\d-[A-Za-z]{3}-\d{4} \d\d:\d\d)',
    re.IGNORECASE,
)

_CAP_XML_NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}

_CAP_SEVERITY_ORDER = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1,
                       "Unknown": 0}


def _parse_cap_xml(xml_bytes):
    """Extract every currently-valid Actual alert from one CAP XML.
    Returns [] if the file is a nothing-to-report update or already
    expired. One <alert> can carry many <info> blocks (per severity or
    language) — we keep the Czech ones with severity > Unknown, and
    dedup identical events across areas so the banner doesn't repeat."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    status = (root.findtext("c:status", "", _CAP_XML_NS) or "").strip()
    if status not in ("Actual", ""):
        return []

    now = datetime.now(timezone.utc)
    out = []
    for info in root.findall("c:info", _CAP_XML_NS):
        lang = (info.findtext("c:language", "", _CAP_XML_NS) or "").lower()
        if lang and not lang.startswith("cs"):
            continue
        severity = info.findtext("c:severity", "", _CAP_XML_NS) or "Unknown"
        if _CAP_SEVERITY_ORDER.get(severity, 0) < 1:
            continue

        expires = info.findtext("c:expires", "", _CAP_XML_NS)
        if expires:
            try:
                exp = datetime.fromisoformat(expires)
                if exp < now:
                    continue
            except ValueError:
                pass

        onset = info.findtext("c:onset", "", _CAP_XML_NS)
        event = info.findtext("c:event", "", _CAP_XML_NS) or ""
        headline = info.findtext("c:headline", "", _CAP_XML_NS) or event
        description = info.findtext("c:description", "", _CAP_XML_NS) or ""
        instruction = info.findtext("c:instruction", "", _CAP_XML_NS) or ""

        areas = []
        for area in info.findall("c:area", _CAP_XML_NS):
            desc = area.findtext("c:areaDesc", "", _CAP_XML_NS)
            if desc:
                areas.append(desc)

        out.append({
            "event":       event,
            "headline":    headline,
            "severity":    severity,
            "onset":       onset or None,
            "expires":     expires or None,
            "description": description,
            "instruction": instruction,
            "areas":       areas,
        })
    return out


@app.get("/api/radar/alerts")
def radar_alerts():
    """Currently-valid ČHMÚ CAP alerts, deduped by event+severity across
    files (later Update supersedes earlier). CHMÚ writes many bulky XML
    files (~2 MB each, one every ~50 min for the meteo channel and
    daily for HAMR drought), so we only fetch the very newest _50_ and
    _70_ file — a fresh Update always carries the full picture."""
    hit = _cache_get("alerts")
    if hit is not None:
        return hit

    try:
        r = requests.get(CHMI_ALERTS_LIST, timeout=5.0)
        r.raise_for_status()
        rows = _CAP_ROW_RE.findall(r.text)
    except Exception as e:
        log.warning("CHMI alerts listing failed: %s", e)
        return JSONResponse({"error": "upstream fetch failed"}, status_code=502)

    parsed = []
    for fname, mtime in ((f, m) for f, ch, m in rows):
        try:
            parsed.append((datetime.strptime(mtime, "%d-%b-%Y %H:%M"), fname))
        except ValueError:
            continue
    parsed.sort()

    # Pick the newest file per channel prefix (50 = meteo, 70 = HAMR
    # drought). Each is an "Update" carrying the current world state.
    latest_by_channel = {}
    for dt, fname in parsed:
        m = re.match(r'alert_cap_(\d+)_', fname)
        if not m:
            continue
        latest_by_channel[m.group(1)] = fname

    alerts = []
    for fname in latest_by_channel.values():
        try:
            xml_r = requests.get(CHMI_ALERTS_LIST + fname, timeout=6.0)
            xml_r.raise_for_status()
            alerts.extend(_parse_cap_xml(xml_r.content))
        except Exception as e:
            log.warning("CHMI CAP fetch %s failed: %s", fname, e)

    alerts.sort(key=lambda a: (-_CAP_SEVERITY_ORDER.get(a["severity"], 0),
                                a["event"]))
    payload = {"count": len(alerts), "alerts": alerts,
               "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    _cache_put("alerts", payload, CHMI_ALERTS_TTL)
    return payload


# ---- PWA assets --------------------------------------------------------

@app.get("/manifest.json")
def manifest():
    with open(os.path.join(BASE_DIR, "static", "manifest.json"), "rb") as f:
        body = f.read()
    return Response(
        content=body,
        media_type="application/manifest+json",
    )


@app.get("/manifest.tablet.json")
def manifest_tablet():
    """Tablet PWA manifest, served from root with the proper
    application/manifest+json type so Chrome installs a real WebAPK
    (fullscreen) rather than a plain home-screen shortcut."""
    with open(os.path.join(BASE_DIR, "static", "manifest.tablet.json"), "rb") as f:
        body = f.read()
    return Response(
        content=body,
        media_type="application/manifest+json",
    )


@app.get("/service-worker.js")
def service_worker():
    with open(os.path.join(BASE_DIR, "static", "service-worker.js"), "rb") as f:
        body = f.read()
    return Response(
        content=body,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/sw-tablet.js")
def sw_tablet():
    """Dedicated SW for the tablet PWA, served from root so it can claim
    the /tablet.html scope (Service-Worker-Allowed). Isolated from the
    main site's service-worker.js."""
    with open(os.path.join(BASE_DIR, "static", "sw-tablet.js"), "rb") as f:
        body = f.read()
    return Response(
        content=body,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


# ---- WebSocket JSON-RPC ------------------------------------------------

@app.websocket("/websocket")
async def websocket_endpoint(ws: WebSocket):
    """Drop-in port of the Tornado WebSocket handler.

    Each incoming message is a JSON-RPC envelope; we look up the named
    function in `methods` and call it. Methods are sync (heavy InfluxDB /
    tinytuya / Redis work), so we dispatch via `run_in_threadpool` to
    keep the event loop healthy when one call hangs.
    """
    await ws.accept()
    try:
        while True:
            message = await ws.receive_text()
            try:
                json_rpc = json.loads(message)
            except json.JSONDecodeError:
                log.error("bad ws frame: %r", message[:200])
                continue

            method_name = json_rpc.get("method")
            params = json_rpc.get("params", {}) or {}
            router = json_rpc.get("router")
            req_id = json_rpc.get("id")

            try:
                fn = getattr(methods, method_name)
                result = await run_in_threadpool(fn, **params)
                error = None
            except Exception:
                result = traceback.format_exc()
                error = 1
                log.error("Error in method %s: %s", method_name, result)

            await ws.send_text(json.dumps(
                {"result": result, "error": error,
                 "router": router, "id": req_id},
                separators=(",", ":"),
            ))
    except WebSocketDisconnect:
        return
