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
import time
import traceback
from datetime import datetime, timedelta

import pandas as pd
import paho.mqtt.client as mqtt_client
import tinytuya
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
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
    lights, devices = [], []

    for id_, values in conf.Lights.items.items():
        value = conf.Lights.status(values["ip"], values["port"])
        log.info(">>> %s", value)
        lights.append({
            "id": id_,
            "name": values["name"],
            "type": "relay",
            "value": value,
        })

    for _id, device in conf.Tuya.devices.items():
        if not device.get("name") or not device.get("ip"):
            continue
        d = tinytuya.OutletDevice(
            dev_id=device["id"], address=device["ip"],
            local_key=device["key"], version=device["ver"])
        d.set_socketTimeout(1)
        d.set_socketRetryLimit(0)
        try:
            status = d.status()
            value = status.get("dps", {}).get("1")
        except Exception as e:
            log.warning("tuya %s status failed: %s", device["name"], e)
            value = None
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

    flat = {}
    for k, v in body.items():
        if k == "pack_id":
            continue
        if k == "cells_mv" and isinstance(v, list):
            for i, mv in enumerate(v):
                flat[f"cell_{i+1:02d}_mv"] = int(mv)
            flat["cell_count_reported"] = len(v)
            continue
        if k == "temps_dC" and isinstance(v, list):
            for i, t in enumerate(v):
                # decicelsius on the wire — store as °C float
                flat[f"temp_{i+1}_c"] = float(t) / 10.0
            continue
        if isinstance(v, bool):
            flat[k] = int(v)
        elif isinstance(v, (int, float, str)):
            flat[k] = v
    flat["pack_id"] = pack_id
    flat["client_ip"] = _client_ip(request)

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


# ---- PWA assets --------------------------------------------------------

@app.get("/manifest.json")
def manifest():
    with open(os.path.join(BASE_DIR, "static", "manifest.json"), "rb") as f:
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
