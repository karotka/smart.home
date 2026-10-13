"""Solar production forecast → MQTT.

Fetches irradiance from Open-Meteo (free, no API key), converts it to an
expected production curve, and publishes the result as one retained JSON
message on `home/forecast/solar`. The tablet panel subscribes to that and
draws it; nothing else is needed on the consumer side.

Run from a systemd timer (hourly) — see service/forecast_solar.{service,timer}.

## What "expected" means here

The conversion is a single fitted number:

    F = kWh produced per kWh/m² of plane-of-array irradiance

and then `expected_kW(h) = GTI(h) [W/m²] / 1000 * F`.

F is refitted on every run from the last `fit_days` days, so it tracks the
season (the gain of a shallow 17° roof over horizontal irradiance changes a
lot between December and June) without anyone having to maintain a table.
Fitting it beats computing it from kWp × performance ratio, because it also
absorbs whatever systematic offset sits between the model's irradiance and
what this particular roof and these particular inverters report.

**F is the upper envelope of the daily ratio, not its mean** — and that choice
is the whole point. The inverters are demand-following: on a bright day with a
full battery they take only what the house and the charge limit can absorb and
leave the rest on the panels, so the measured ratio on exactly the best days
comes out *low*. Observed 2026-10, the daily ratio ran 7.7 on the clearest days
against ~13.8 on overcast ones, purely from curtailment. Averaging that spread
would forecast the curtailment back at us; taking a high percentile recovers
what the array can deliver when something is there to absorb it.

So the published curve is **potential**, and `act_kw` / `actual_kwh` alongside
it is **harvest**. The gap between them is curtailed energy — the cheapest
input the system has, and the thing ENERGY_CONTROL.md exists to go after.

Days where either inverter reported nothing are dropped from the fit: that is
a wedged monitor (it happens — see the CH341 notes in CLAUDE.md), not weather,
and it would drag the envelope down. If nothing survives the filter, F falls
back to `fallback_factor` from the config.
"""

import configparser
import datetime as dt
import json
import logging
import os
import urllib.parse
import urllib.request
from logging.handlers import RotatingFileHandler

import paho.mqtt.client as mqtt


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOPIC = "home/forecast/solar"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 20

DAILY_VARS = ["shortwave_radiation_sum", "sunshine_duration", "cloud_cover_mean",
              "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
              "weather_code"]
HOURLY_VARS = ["global_tilted_irradiance", "temperature_2m", "cloud_cover"]

# Czech day abbreviations, Monday-first to match date.weekday().
DOW_CS = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

# invertor.py's DEVICE_CONFIG positions. Both units feed the same measurement
# with no tags, so the only way to separate them is the deviceNumber *field*.
DEVICES = ["first", "second"]


def _load_config():
    cfg = configparser.ConfigParser()
    # conf/config.ini is tracked in a *public* repo, so the site's exact
    # coordinates live in forecast.local.ini instead, which is gitignored.
    # Later files win, so the local one overrides whatever is in the tracked
    # defaults.
    cfg.read([os.path.join(BASE_DIR, "conf/config.ini"),
              os.path.join(BASE_DIR, "conf/forecast.local.ini")])
    return cfg


def _setup_logging():
    log_path = os.path.join(BASE_DIR, "log/forecast_solar.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    handler = RotatingFileHandler(log_path, backupCount=3, maxBytes=1_000_000)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s forecast_solar [%(process)d] %(levelname)s %(message)s",
        "%b %d %H:%M:%S"))
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "smart.home/forecast_solar"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------- Open-Meteo

def fetch_meteo(lat, lon, tilt, azimuth, past_days, forecast_days, tz):
    """Daily outlook + hourly tilted irradiance, in local time."""
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "daily": ",".join(DAILY_VARS),
        "hourly": ",".join(HOURLY_VARS),
        # Open-Meteo's azimuth convention: 0 = south, -90 = east, +90 = west.
        "tilt": tilt, "azimuth": azimuth,
        "timezone": tz,
        "past_days": past_days, "forecast_days": forecast_days,
    })
    return _get_json(f"{OPEN_METEO}?{q}")


# ------------------------------------------------------------------ InfluxDB

def _influx(host, port, db, query, epoch="s"):
    q = urllib.parse.urlencode({"db": db, "q": query, "epoch": epoch})
    data = _get_json(f"http://{host}:{port}/query?{q}")
    series = data.get("results", [{}])[0].get("series")
    if not series:
        return [], []
    return series[0]["columns"], series[0]["values"]


def actual_daily_kwh(influx, days):
    """{date -> {unit -> kWh}} harvested.

    Kept per unit rather than pre-summed so the fit can tell a dark day apart
    from a day where one monitor was wedged and silently contributed zero.
    `invertor_daily` carries one row per unit per day, keyed at UTC midnight,
    with the unit in the `devNumber` field.
    """
    cols, rows = _influx(*influx, f"SELECT solarPowerIn, devNumber FROM invertor_daily "
                                  f"WHERE time > now() - {days}d")
    if not rows:
        return {}
    i_val, i_dev = cols.index("solarPowerIn"), cols.index("devNumber")
    out = {}
    for row in rows:
        wh, dev = row[i_val], row[i_dev]
        if wh is None or not dev:
            continue
        day = dt.datetime.fromtimestamp(row[0], dt.timezone.utc).date().isoformat()
        out.setdefault(day, {})[dev] = wh / 1000.0
    return out


def day_total(per_dev):
    return sum(per_dev.values()) if per_dev else None


def actual_hourly_kw(influx, tz):
    """[(hour_iso, kW)] harvested today, summed over both inverters.

    QPIGS reports PV voltage and current separately; the product is the power.
    Averaging them separately is safe because the string voltage is nearly
    constant within an hour while the current is what moves.
    """
    totals = {}
    for dev in DEVICES:
        cols, rows = _influx(*influx,
                             f"SELECT mean(solarVoltage) AS v, mean(solarCurrent) AS i "
                             f"FROM invertor WHERE deviceNumber = '{dev}' "
                             f"AND time > now() - 30h GROUP BY time(1h) tz('{tz}')")
        if not rows:
            continue
        i_v, i_i = cols.index("v"), cols.index("i")
        for row in rows:
            v, a = row[i_v], row[i_i]
            if v is None or a is None:
                continue
            ts = dt.datetime.fromtimestamp(row[0]).strftime("%Y-%m-%dT%H:00")
            totals[ts] = totals.get(ts, 0.0) + v * a / 1000.0
    return totals


# -------------------------------------------------------------------- the fit

def hourly_by_day(hourly):
    """{date -> [(hour_iso, gti_W_m2)]} from the flat Open-Meteo arrays."""
    out = {}
    times = hourly.get("time", [])
    gti = hourly.get("global_tilted_irradiance", [])
    for i, t in enumerate(times):
        v = gti[i] if i < len(gti) else None
        out.setdefault(t[:10], []).append((t, v or 0.0))
    return out


def percentile(values, pct):
    """Linear-interpolated percentile. Avoids a numpy dependency on the host."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * pct / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def fit_factor(by_day, actual, today, fit_days, min_poa, pct, fallback):
    """kWh per kWh/m² of plane-of-array irradiance — the upper envelope.

    Only closed days count: today is still in progress, a day with almost no
    sun carries no information while being very good at dividing by zero, and
    a day where an inverter reported nothing is a dead monitor, not weather.
    """
    ratios, used = {}, []
    for day in sorted(by_day, reverse=True):
        if day >= today or day not in actual:
            continue
        poa = sum(w for _, w in by_day[day]) / 1000.0   # W/m² per hour -> kWh/m²
        if poa < min_poa:
            continue
        per_dev = actual[day]
        if len(per_dev) < len(DEVICES) or any(v <= 0 for v in per_dev.values()):
            continue
        ratios[day] = day_total(per_dev) / poa
        used.append(day)
        if len(used) >= fit_days:
            break
    if not ratios:
        return float(fallback), "fallback", [], {}
    return (percentile(list(ratios.values()), pct),
            f"p{pct:g}/{len(ratios)}d", sorted(used), ratios)


# ----------------------------------------------------------------- the payload

def build(cfg_f, meteo, actual_d, actual_h):
    tz = cfg_f.get("timezone", "Europe/Prague")
    today = dt.datetime.now().date().isoformat()
    by_day = hourly_by_day(meteo.get("hourly", {}))

    factor, source, used, ratios = fit_factor(
        by_day, actual_d, today,
        fit_days=int(cfg_f.get("fit_days", 7)),
        min_poa=float(cfg_f.get("fit_min_poa", 0.8)),
        pct=float(cfg_f.get("fit_percentile", 80)),
        fallback=cfg_f.get("fallback_factor", 14.0))

    daily = meteo.get("daily", {})
    days = []
    for i, day in enumerate(daily.get("time", [])):
        poa = sum(w for _, w in by_day.get(day, [])) / 1000.0

        def d(key, scale=1.0):
            arr = daily.get(key) or []
            v = arr[i] if i < len(arr) else None
            return None if v is None else round(v * scale, 2)

        days.append({
            "date": day,
            "dow": DOW_CS[dt.date.fromisoformat(day).weekday()],
            "today": day == today,
            "past": day < today,
            "ghi_kwh_m2": d("shortwave_radiation_sum", 1 / 3.6),   # API gives MJ/m²
            "poa_kwh_m2": round(poa, 2),
            "sun_h": d("sunshine_duration", 1 / 3600.0),
            "cloud_pct": d("cloud_cover_mean"),
            "tmin": d("temperature_2m_min"),
            "tmax": d("temperature_2m_max"),
            "precip_mm": d("precipitation_sum"),
            "wcode": d("weather_code"),
            "est_kwh": round(poa * factor, 1),
            "actual_kwh": (round(day_total(actual_d[day]), 1)
                           if day in actual_d else None),
        })

    # Hourly curve for today + tomorrow only — that's the horizon anyone
    # actually acts on, and it keeps the retained message small.
    horizon = [today, (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()]
    times, exp_kw, act_kw = [], [], []
    for day in horizon:
        for t, w in by_day.get(day, []):
            times.append(t)
            exp_kw.append(round(w / 1000.0 * factor, 2))
            a = actual_h.get(t)
            act_kw.append(None if a is None else round(a, 2))

    return {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "tz": tz,
        "lat": meteo.get("latitude"), "lon": meteo.get("longitude"),
        "kwp": float(cfg_f.get("kwp", 0) or 0),
        "factor": round(factor, 2),
        "factor_source": source,
        "factor_days": used,
        # The spread is the curtailment signal: a low ratio on a bright day
        # means the array had more to give than anything was willing to take.
        "factor_ratios": {d: round(r, 2) for d, r in sorted(ratios.items())},
        "days": days,
        "hours": {"t": times, "exp_kw": exp_kw, "act_kw": act_kw},
    }


def publish(cfg, payload):
    client = mqtt.Client("forecast-solar")
    client.connect(cfg["Mqtt"].get("host"), int(cfg["Mqtt"].get("port")), keepalive=30)
    client.loop_start()
    info = client.publish(TOPIC, json.dumps(payload), qos=1, retain=True)
    info.wait_for_publish()
    client.loop_stop()
    client.disconnect()


def main():
    _setup_logging()
    cfg = _load_config()
    f = cfg["Forecast"] if cfg.has_section("Forecast") else {}
    tz = f.get("timezone", "Europe/Prague")
    influx = (cfg["Influx"].get("host"), cfg["Influx"].get("port"), cfg["Influx"].get("db"))

    meteo = fetch_meteo(
        f.get("latitude"), f.get("longitude"),
        f.get("tilt", 17), f.get("azimuth", 0),
        int(f.get("past_days", 3)), int(f.get("forecast_days", 5)), tz)

    try:
        actual_d = actual_daily_kwh(influx, int(f.get("fit_days", 7)) + 3)
        actual_h = actual_hourly_kw(influx, tz)
    except Exception:
        # A forecast without the actuals overlay is still worth publishing —
        # it just falls back to the configured factor.
        logging.exception("influx read failed; publishing forecast without actuals")
        actual_d, actual_h = {}, {}

    payload = build(f, meteo, actual_d, actual_h)
    publish(cfg, payload)

    nxt = next((d for d in payload["days"] if not d["past"] and not d["today"]), None)
    logging.info("published: factor=%.2f (%s) today=%.1f kWh next=%s %.1f kWh",
                 payload["factor"], payload["factor_source"],
                 next((d["est_kwh"] for d in payload["days"] if d["today"]), 0.0),
                 nxt["date"] if nxt else "-", nxt["est_kwh"] if nxt else 0.0)


if __name__ == "__main__":
    main()
