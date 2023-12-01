#!/home/karotka/influx2.python/bin/python3

import influxdb_client, os, time
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

token = os.environ.get("INFLUXDB_TOKEN")
org = "karotka"
url = "http://192.168.0.224:8087"

write_client = influxdb_client.InfluxDBClient(url=url, token=token, org=org)

