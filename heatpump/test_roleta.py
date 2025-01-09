import os
import sys
import tinytuya
import json

# Address = 192.168.1.55   Device ID = bf9a362c8c6c46ae9aotgd (len:22)  Local Key = !4`pi;Y@~v~ulV`{  Version = 3.3  Type = default, MAC = fc:67:1f:db:43:33
d1 = tinytuya.OutletDevice(dev_id="bf5a88a6a9bf0bdd33saat", address="192.168.0.171", version="3.3")

d = d1.status()["dps"]
print (d)

