#!/bin/bash
# Aggregate runner. Cron-friendly: paths are derived relative to the repo
# root so the same script works on any host.

set -x

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INVERTOR_AGG="$SCRIPT_DIR/aggregate.py"
HEATPUMP_AGG="$REPO_ROOT/heatpump/aggregate.py"

case $1 in

    "today")
        /usr/bin/python3 "$INVERTOR_AGG" --mode=daily --date=$(date +%Y-%m-%d)
        ;;

    "yesterday")
        /usr/bin/python3 "$INVERTOR_AGG" --mode=daily --date=$(date -d "now -1 days" +%Y-%m-%d)
        ;;

    "this-month")
        /usr/bin/python3 "$INVERTOR_AGG" --mode=monthly --date=$(date +%Y-%m)
        ;;

    "last-month")
        /usr/bin/python3 "$INVERTOR_AGG" --mode=monthly --date=$(date -d "now -1 months" +%Y-%m)
        ;;

    "hp-hourly")
        /usr/bin/python3 "$HEATPUMP_AGG" --mode=hourly --date=$(date +%Y-%m-%d)
        ;;

esac
