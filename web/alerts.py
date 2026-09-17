"""Background alert evaluation.

Called every tick by checkerd (reloaded like checker), but does real work only
every EVAL_EVERY_S seconds. Rules live in conf/alerts.json (mtime-reloaded, so
edits apply live). Results are written to Redis so the (cheap) `alerts_status`
web method just reads them back for the tablet's Alerty tab.

Redis keys:
  alerts_view   JSON — what the UI reads: {ts, summary, active[], rules[]}
  alerts_state  JSON — internal hold/since bookkeeping across ticks
"""
import json
import os
import time

from config import conf
import methods

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conf", "alerts.json")
EVAL_EVERY_S = 15

_rules_cache = {"mtime": 0, "rules": []}
_last_eval = {"t": 0}

_OPS = {
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _load_rules():
    try:
        mtime = os.stat(RULES_PATH).st_mtime
    except OSError:
        return []
    if mtime != _rules_cache["mtime"]:
        try:
            with open(RULES_PATH) as f:
                _rules_cache["rules"] = json.load(f).get("rules", [])
            _rules_cache["mtime"] = mtime
        except Exception:
            pass  # keep the last good copy on a malformed edit
    return _rules_cache["rules"]


def _fmt(v):
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)


def _battery_signals():
    """Per-pack signal dict with a few derived fields for the rules."""
    out = []
    for p in methods.battery_packs().get("packs", []):
        temps = [t for t in (p.get("temp_1_c"), p.get("temp_2_c"), p.get("temp_3_c")) if t is not None]
        sig = dict(p)
        sig["temp_max_c"] = max(temps) if temps else None
        sig["temp_min_c"] = min(temps) if temps else None
        sig["charging"] = 1 if (p.get("current_a") or 0) > 0.5 else 0
        out.append(sig)
    return out


def _conditions_met(sig, rule):
    """All conditions true? Return (ok, primary_value) where primary_value is
    the value of the first condition's field (used for the message/threshold)."""
    primary = None
    for i, c in enumerate(rule.get("conditions", [])):
        val = sig.get(c.get("field"))
        if i == 0:
            primary = val
        if val is None:
            return False, primary
        op = _OPS.get(c.get("op"))
        try:
            if op is None or not op(val, c.get("threshold")):
                return False, primary
        except Exception:
            return False, primary
    return True, primary


def evaluate(logger=None):
    """Throttled evaluation. Safe to call every tick; never raises upward
    into the heating loop (checkerd wraps it, but we also swallow here)."""
    now = time.time()
    if now - _last_eval["t"] < EVAL_EVERY_S:
        return
    _last_eval["t"] = now

    try:
        db = conf.db.conn
        rules = [r for r in _load_rules() if r.get("enabled", True)]
        signals = _battery_signals()

        try:
            old_state = json.loads(db.get("alerts_state") or "{}")
        except Exception:
            old_state = {}

        new_state, active = {}, []
        for rule in rules:
            for sig in signals:      # scope: per_pack (only battery for now)
                pack_id = sig.get("pack_id", "?")
                ok, primary = _conditions_met(sig, rule)
                if not ok:
                    continue
                key = "%s|%s" % (rule["id"], pack_id)
                prev = old_state.get(key, {})
                pending_since = prev.get("pending_since", now)
                active_since = prev.get("active_since")
                if active_since is None and (now - pending_since) >= rule.get("hold_s", 0):
                    active_since = now
                new_state[key] = {"pending_since": pending_since,
                                  "active_since": active_since, "value": primary}
                if active_since is None:
                    continue
                thr = rule["conditions"][0].get("threshold")
                unit = rule.get("unit", "")
                try:
                    msg = rule.get("message", rule["name"]).format(
                        pack_id=pack_id, value=_fmt(primary), threshold=_fmt(thr), unit=unit)
                except Exception:
                    msg = rule["name"]
                active.append({
                    "id": key, "rule_id": rule["id"], "pack_id": pack_id,
                    "name": rule["name"], "severity": rule.get("severity", "warning"),
                    "category": rule.get("category", "battery"),
                    "message": msg, "value": primary, "threshold": thr,
                    "unit": unit, "since": int(active_since),
                })

        crit = sum(1 for a in active if a["severity"] == "critical")
        warn = sum(1 for a in active if a["severity"] != "critical")
        active.sort(key=lambda a: (0 if a["severity"] == "critical" else 1, a["rule_id"]))

        view = {
            "ts": int(now),
            "summary": {"critical": crit, "warning": warn,
                        "ok": (len(active) == 0), "packs": len(signals)},
            "active": active,
            "rules": [{"id": r["id"], "name": r["name"],
                       "severity": r.get("severity", "warning"),
                       "category": r.get("category", "battery"),
                       "enabled": r.get("enabled", True)} for r in rules],
        }
        db.set("alerts_state", json.dumps(new_state))
        db.set("alerts_view", json.dumps(view))
    except Exception as e:
        if logger:
            logger.warning("alerts.evaluate failed: %s" % e)
