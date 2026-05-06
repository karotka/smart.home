#!/usr/bin/python3
"""
Dump / decode / diff Tuya cloud parameter_group_* values for the heat pump.

Workflow for reverse engineering an unknown parameter index:
    1. heatpump/dump_params.py dump  before.json
    2. change a single setting in the Tuya / Smart Life app
    3. heatpump/dump_params.py dump  after.json
    4. heatpump/dump_params.py diff  before.json after.json
       -> shows which group / int32 index changed (and from what to what)

Subcommands:
    dump   <out.json>           pull a fresh snapshot from the cloud
    decode <in.json>            print decoded int32 arrays for all groups
    diff   <a.json> <b.json>    show indices that differ between two snapshots
"""

import argparse
import base64
import json
import os
import struct
import sys
from datetime import datetime

import tinytuya


HP_DEVICE_ID = "bf06f140ee20807fdaalyq"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_AUTH_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "web", "tinytuya.json"))


def load_auth(path=DEFAULT_AUTH_PATH):
    if not os.path.exists(path):
        sys.exit(f"auth file not found: {path}")
    with open(path) as f:
        return json.load(f)


def cloud_snapshot(auth):
    api = tinytuya.Cloud(
        apiRegion=auth.get("apiRegion", "eu"),
        apiKey=auth["apiKey"],
        apiSecret=auth["apiSecret"],
    )
    res = api.getstatus(HP_DEVICE_ID)
    if not isinstance(res, dict) or not res.get("success", False):
        msg = res.get("msg") if isinstance(res, dict) else "no response"
        sys.exit(f"Tuya cloud error: {msg}")
    return res["result"]


def decode_group(b64):
    raw = base64.b64decode(b64)
    n = len(raw) // 4
    return list(struct.unpack(f">{n}i", raw[: n * 4]))


def parameter_groups(payload):
    """Yield (code, base64_value, [int32...]) for each parameter_group_* entry."""
    for item in payload:
        code = item.get("code", "")
        if code.startswith("parameter_group_"):
            yield code, item["value"], decode_group(item["value"])


def cmd_dump(args):
    auth = load_auth(args.auth)
    payload = cloud_snapshot(auth)
    out = {
        "device_id": HP_DEVICE_ID,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "raw": payload,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2, default=str)
    n_groups = sum(1 for _ in parameter_groups(payload))
    print(f"saved {args.output}  ({len(payload)} codes, {n_groups} parameter groups)")


def cmd_decode(args):
    with open(args.input) as f:
        snap = json.load(f)
    payload = snap.get("raw", snap)
    print(f"# {snap.get('fetched_at', '?')}")
    for code, _b64, ints in parameter_groups(payload):
        print(f"\n{code}:")
        for i, v in enumerate(ints):
            print(f"  [{i:2d}] = {v}")


def cmd_diff(args):
    with open(args.a) as f:
        a = json.load(f)
    with open(args.b) as f:
        b = json.load(f)

    a_groups = {code: ints for code, _, ints in parameter_groups(a.get("raw", a))}
    b_groups = {code: ints for code, _, ints in parameter_groups(b.get("raw", b))}

    print(f"A: {a.get('fetched_at', '?')}")
    print(f"B: {b.get('fetched_at', '?')}")
    print()

    found = False
    for code in sorted(set(a_groups) | set(b_groups)):
        av = a_groups.get(code, [])
        bv = b_groups.get(code, [])
        for i in range(max(len(av), len(bv))):
            x = av[i] if i < len(av) else None
            y = bv[i] if i < len(bv) else None
            if x != y:
                found = True
                print(f"{code}[{i:2d}]: {x} -> {y}  (delta {None if None in (x, y) else y - x})")

    # Also diff non-parameter-group scalar codes
    a_scalars = {item["code"]: item.get("value") for item in a.get("raw", a)
                 if isinstance(item, dict) and not item.get("code", "").startswith("parameter_group_")}
    b_scalars = {item["code"]: item.get("value") for item in b.get("raw", b)
                 if isinstance(item, dict) and not item.get("code", "").startswith("parameter_group_")}
    for code in sorted(set(a_scalars) | set(b_scalars)):
        x, y = a_scalars.get(code), b_scalars.get(code)
        if x != y:
            found = True
            print(f"{code}: {x} -> {y}")

    if not found:
        print("(no differences)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--auth", default=DEFAULT_AUTH_PATH,
                   help=f"path to tinytuya.json (default: {DEFAULT_AUTH_PATH})")
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("dump", help="pull fresh snapshot from cloud and write JSON")
    pd.add_argument("output")
    pd.set_defaults(func=cmd_dump)

    pde = sub.add_parser("decode", help="show decoded int32 arrays for all parameter groups")
    pde.add_argument("input")
    pde.set_defaults(func=cmd_decode)

    pdi = sub.add_parser("diff", help="show fields that changed between two snapshots")
    pdi.add_argument("a")
    pdi.add_argument("b")
    pdi.set_defaults(func=cmd_diff)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
