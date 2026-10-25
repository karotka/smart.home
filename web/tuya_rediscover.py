"""Re-discover current IPs and local keys of every Tuya device.

Listens for Tuya broadcasts on UDP 6666/6667 long enough to catch
each device, then maps device-id to current IP. When --write is set
we patch conf/snapshot.json in place — the web app's lazy reload
(mtime-watched on conf.Tuya) picks up the new values on next access,
no container restart needed.

Two things can silently cut us off from a device, and this job
repairs both:

  * **the IP moves** — these units have no static-IP option in the
    app and DHCP renumbers them. Caught from the broadcast.
  * **the local key changes** — re-pairing a device in the Tuya app
    rotates it. Nothing on the wire tells us; tinytuya just answers
    `Err 914 Check device key or version` and the device looks dead
    while it is sitting there happily broadcasting. That is exactly
    how "Aqua" stopped switching in October 2026. Caught by diffing
    against the cloud device list.

The cloud half is best-effort: no `tinytuya.json`, no network or a
throttled API must not stop the IP refresh, which works offline.

Designed to be invoked by a systemd .timer (see
service/tuya_rediscover.timer); the per-run cost is one ~12 s
broadcast listen, one cloud call and a stat() call from the web app,
so we can run it hourly without weighing on checker.py's 15 s tick.

Keys are secrets: this prints only whether one changed, never its
value, because the output lands in the journal.

Usage:
  python3 tuya_rediscover.py                 # report only
  python3 tuya_rediscover.py --write         # update snapshot.json
  python3 tuya_rediscover.py --no-cloud      # skip the key check
"""
import json
import os
import sys
import tinytuya

# Resolved relative to the script so the timer can call us with cwd /.
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_PATH = os.path.join(HERE, "conf", "snapshot.json")
CLOUD_AUTH_PATH = os.path.join(HERE, "tinytuya.json")
HP_DEVICE_ID = "bf06f140ee20807fdaalyq"


def cloudKeys():
    """{device_id: local_key} from the Tuya cloud, or {} if unavailable.

    Every failure path returns {} rather than raising: the caller
    falls back to an IP-only run, which is what this job did before
    keys were checked at all. A dead cloud must never cost us the
    part that works on the LAN alone.
    """
    try:
        with open(CLOUD_AUTH_PATH) as f:
            auth = json.load(f)
    except (OSError, ValueError) as e:
        print("cloud: no usable %s (%s) — skipping key check"
              % (os.path.basename(CLOUD_AUTH_PATH), e))
        return {}

    try:
        cloud = tinytuya.Cloud(
            apiRegion=auth.get("apiRegion"),
            apiKey=auth.get("apiKey"),
            apiSecret=auth.get("apiSecret"),
            apiDeviceID=auth.get("apiDeviceID"),
        )
        devices = cloud.getdevices()
    except Exception as e:
        print("cloud: lookup failed (%s) — skipping key check" % e)
        return {}

    # getdevices() hands back an error *dict* instead of raising when
    # the API refuses (bad signature, quota, clock skew), so the happy
    # path has to be recognised by shape, not by the absence of an
    # exception.
    if not isinstance(devices, list):
        print("cloud: lookup refused (%s) — skipping key check"
              % (devices.get("Error") if isinstance(devices, dict) else devices))
        return {}

    return {d["id"]: d["key"] for d in devices if d.get("id") and d.get("key")}


def main():
    write = "--write" in sys.argv
    use_cloud = "--no-cloud" not in sys.argv

    with open(SNAPSHOT_PATH) as f:
        snap = json.load(f)
    by_id = {d["id"]: d for d in snap.get("devices", [])}

    print("=== Scanning LAN for Tuya broadcasts (12 s) ===")
    # maxretry around 12 has been enough to catch every responsive
    # device we have; raising it isn't free (each retry is a fresh
    # listen window) so 12 is the sweet spot.
    found = tinytuya.deviceScan(verbose=False, maxretry=12)
    found_by_id = {}
    for ip, dev in found.items():
        did = dev.get("gwId") or dev.get("id")
        if did:
            found_by_id[did] = ip
    print("found %d unique device(s) on the wire" % len(found_by_id))
    print()

    changes = []
    for did, dev in by_id.items():
        old_ip = dev.get("ip")
        new_ip = found_by_id.get(did)
        name = dev.get("name", "?")
        if new_ip and new_ip != old_ip:
            marker = " (HEAT PUMP)" if did == HP_DEVICE_ID else ""
            print("CHANGE  %-28s %s -> %s%s" % (name[:28], old_ip, new_ip, marker))
            changes.append((did, old_ip, new_ip))
            dev["ip"] = new_ip
        elif new_ip:
            print("same    %-28s %s" % (name[:28], old_ip))
        else:
            print("missing %-28s last=%s (not seen on wire)" % (name[:28], old_ip))

    for did, ip in found_by_id.items():
        if did not in by_id:
            pkey = found.get(ip, {}).get("productKey", "?")
            print("new     id=%s ip=%s pkey=%s" % (did, ip, pkey))

    print()
    print("%d device(s) need an IP update" % len(changes))

    rekeyed = []
    if use_cloud:
        print()
        print("=== Checking local keys against the cloud ===")
        for did, key in cloudKeys().items():
            dev = by_id.get(did)
            # Devices the cloud knows and the snapshot doesn't are
            # cameras and sensors we never drive locally — not ours
            # to add here.
            if dev is None or dev.get("key") == key:
                continue
            print("REKEY   %-28s local key rotated" % dev.get("name", "?")[:28])
            dev["key"] = key
            rekeyed.append(did)
        print("%d device(s) need a key update" % len(rekeyed))

    if not changes and not rekeyed:
        return
    if write:
        with open(SNAPSHOT_PATH, "w") as f:
            json.dump(snap, f, indent=4, ensure_ascii=False)
        print("snapshot.json updated (mtime bump signals lazy reload in web app)")
    else:
        print("(dry run — re-run with --write to persist)")


if __name__ == "__main__":
    main()
