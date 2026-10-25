from datetime import datetime, date, timedelta
import base64
import pickle
import time


# --- battery state ---------------------------------------------------------
# Live BMS snapshots, written by mqtt_bridge from home/bms/+/snapshot (~1 s).
# This lives in utils rather than in the controller because the panel and the
# controller must not disagree about the battery: when they read different
# numbers, every "why did it do that" question needs both answers before it
# can be asked.
BMS_KEY_PREFIX = "bms_pack_"
BMS_MAX_AGE_S  = 30     # older than this and the pack is not reporting
BMS_MIN_PACKS  = 6      # the whole bank: 5 NMC + the LFP. A sum that is
                        # missing a pack is not the bank's current, and
                        # guessing which one is absent is worse than falling
                        # back to the inverter.


def bmsPacks(db, max_age_s=BMS_MAX_AGE_S) -> list:
    """Live snapshots of every BMS pack that is currently posting.

    Returns a list, possibly empty. A pack that stopped posting drops out by
    Redis TTL, and a stale one is filtered here as well — belt and braces,
    because the caller decides whether it is looking at the whole bank by
    counting these.
    """
    now = time.time()
    packs = []
    try:
        keys = list(db.scan_iter(match=BMS_KEY_PREFIX + "*", count=50))
    except Exception:
        return []
    for key in keys:
        try:
            raw = db.get(key)
            if not raw:
                continue
            p = pickle.loads(raw)
        except Exception:
            continue
        ts = p.get("ts")
        if not ts or (now - float(ts)) > max_age_s:
            continue
        packs.append(p)
    return packs


def batteryState(db, units, battery, min_packs=BMS_MIN_PACKS) -> dict:
    """One measured view of the battery, for the controller and for the UI.

    `units` are the inverter snapshots (used only as a fallback), `battery` is
    conf.Battery. Returns soc / charge_a / discharge_a / volt / power_w /
    source / packs, or None when nothing is reporting — which callers must
    treat as "don't know", never as zero.

    Current and voltage come from the BMS shunts when the whole bank is
    reporting; the inverter is the fallback, and a poor one:

      * its current register is an integer that reads 0 below about 5 A, so
        every slow discharge looked like an idle pack — which is why the
        discharge side of the monitoring appeared not to work at all.
      * charge and discharge are separate registers, and the unit has been
        seen reporting ~9 A in where the shunts summed to less.

    SOC is the bank's charge counted in amp-hours — the packs' own
    remain_mah summed and divided by the nominal capacities in
    conf.Battery.capacity_ah. That became the right answer on 2026-10-25,
    when the LFP was calibrated against a full charge; before that its
    counter was offset by ~30 points and ENERGY_CONTROL.md §7 said to trust
    cell voltage over reported SoC instead.

    The load-compensated voltage map is kept as the fallback for when the
    whole bank is not reporting. Measured against the counters over 13 days
    it tracks within a couple of points below about 60 % and then under-reads
    badly — 53.0 V is 56 % on the voltage scale and 65 % in charge, 54.7 V is
    72 % against 82 %. The error sits exactly where the solar boost and the
    day profile make their decisions, which is why it is no longer what they
    are decided on.
    """
    volt = None
    net_a = None
    source = None
    packs = bmsPacks(db)

    if len(packs) >= min_packs:
        mv = [p.get("total_mv") for p in packs if p.get("total_mv")]
        ma = [p.get("current_ma") for p in packs if p.get("current_ma") is not None]
        if mv and len(ma) == len(packs):
            # One bus measured N times: voltage averages, current sums.
            volt = sum(float(x) for x in mv) / len(mv) / 1000.0
            net_a = sum(float(x) for x in ma) / 1000.0   # + into the pack
            source = "bms"

    if source is None:
        if not units:
            return None
        volt = sum(float(u.get("batteryVoltage", 0)) for u in units) / len(units)
        ci = sum(float(u.get("batteryCurrent", 0)) for u in units)
        di = sum(float(u.get("batteryDischargeCurrent", 0)) for u in units)
        net_a = ci - di
        source = "invertor"

    charge_a = max(0.0, net_a)
    discharge_a = max(0.0, -net_a)

    soc = None
    soc_source = "voltage"
    remain_ah = None
    if source == "bms":
        remain_ah, soc = bankCharge(packs, battery.capacity_ah)
        if soc is not None:
            soc_source = "coulomb"
    if soc is None:
        soc = batterySoc(volt, charge_a, discharge_a,
                         battery.voltage_empty,
                         battery.voltage_full,
                         battery.internal_ohm)

    return {
        "soc": soc,
        "soc_source": soc_source,
        "remain_ah": remain_ah,
        "charge_a": charge_a,
        "discharge_a": discharge_a,
        "volt": volt,
        "power_w": volt * net_a,
        "source": source,
        "packs": len(packs),
    }


def bankCharge(packs, capacity_ah):
    """(remaining Ah, percent) for the bank, or (None, None).

    Every reporting pack must have a nominal capacity configured. A pack
    missing from the table would otherwise contribute charge to the
    numerator and nothing to the denominator, which reads as a fuller
    battery than there is — the one direction this number must never err in,
    because the reserve kept back for a blackout is measured off it.
    """
    if not capacity_ah:
        return None, None
    remain = 0.0
    nominal = 0.0
    for p in packs:
        pack_id = p.get("pack_id")
        mah = p.get("remain_mah")
        if pack_id not in capacity_ah or mah is None:
            return None, None
        remain += float(mah) / 1000.0
        nominal += capacity_ah[pack_id]
    if nominal <= 0:
        return None, None
    return round(remain, 1), max(0.0, min(100.0, 100.0 * remain / nominal))


def toInt(value) -> int:
    try:
        return int(value)
    except TypeError:
        return 0

def toFloat(value) -> float:
    try:
        return float(value)
    except TypeError:
        return .0

def toStr(value) -> str:
    try:
        value = value.decode('ascii')
    except AttributeError:
        value = ""
    return value

def daysBetween(dateFrom, dateTo) -> list:
    delta = dateTo - dateFrom      # as timedelta
    days = list()
    days.append(dateFrom)
    days.append(dateTo)
    for i in range(delta.days):
        days.append(dateFrom + timedelta(days=i))
    return set(days)

def strfdelta(tdelta, fmt):
    d = {"days": tdelta.days}
    d["hours"], rem = divmod(tdelta.seconds, 3600)
    d["minutes"], d["seconds"] = divmod(rem, 60)
    return fmt.format(**d)

def getLogFilenames(logname, days) -> list:
    removed = False
    try:
        d = days.copy()
        now  = datetime.now().replace(minute=0, hour=0, second=0, microsecond=0)
        d.remove(now)
        removed = True
    except KeyError:
        pass

    filenames = ["%s.%s" % (logname, day.strftime("%Y-%m-%d")) for day in d]
    if removed:
        filenames.append(logname)
    return filenames

def getParameterValue(data, parameter_code):
    for item in data:
        if item['code'] == parameter_code:
            return item['value']
    return None

def decode64ToBites(data):
    decoded_bytes = base64.b64decode(data)
    return ''.join(format(byte, '08b') for byte in decoded_bytes)

def base64encode(data):
    return base64.b64encode(data).decode('utf-8')

#def replaceStringRange(original_string, start, end, replacement_string):
#    if start < 0 or end > len(original_string) or start > end:
#        raise ValueError("Invalid range for replacement")
#
#    return original_string[:start] + replacement_string + original_string[end:]

def stringToBytes(data):
    # Convert the final binary string back to a byte array
    byte_array = bytearray()
    for i in range(0, len(data), 8):
        byte = data[i:i+8]
        byte_array.append(int(byte, 2))
    return byte_array


def batterySoc(v_terminal, charge_i, discharge_i, v_empty, v_full, r_ohm):
    """Load-compensated battery state of charge, in percent (0..100).

    The terminal voltage of a battery under discharge drops below its
    open-circuit value by I*R, and rises above it by I*R while charging.
    Back out the open-circuit voltage from the present terminal reading
    so the SOC doesn't dip just because the heat pump kicked on:

        net_i  = discharge_i - charge_i        # >0 sourcing, <0 sinking
        v_open = v_terminal + net_i * r_ohm
        soc    = (v_open - v_empty) / (v_full - v_empty) * 100

    Result is clamped to [0, 100]. Linear mapping is rough on LiPo (the
    middle of the V-SOC curve is flatter than the endpoints) but it's
    plenty for "is the battery full enough to dump surplus into water"
    decisions and matches what the user is used to seeing on
    /invertor.html.
    """
    try:
        v = float(v_terminal)
        ci = float(charge_i)
        di = float(discharge_i)
    except (TypeError, ValueError):
        return None
    net_i = di - ci
    v_open = v + net_i * float(r_ohm)
    pct = (v_open - float(v_empty)) / (float(v_full) - float(v_empty)) * 100
    return max(0.0, min(100.0, pct))


