import os
import sys
import tinytuya
import base64
import json

heat_pump_id = "bf06f140ee20807fdaalyq"

tuyaConf = "tinytuya.json"
with open(tuyaConf, 'r') as tuyaConf:
    tConf = json.load(tuyaConf)

print (tConf)
cloud = tinytuya.Cloud(apiRegion="eu", apiKey = tConf["apiKey"], apiSecret = tConf["apiSecret"] )

print(cloud.getstatus(heat_pump_id))

def replace_range(original_string, start, end, replacement_string):
    if start < 0 or end > len(original_string) or start > end:
        raise ValueError("Invalid range for replacement")

    # Vytvoření nového řetězce
    new_string = original_string[:start] + replacement_string + original_string[end:]

    return new_string


decoded_bytes = base64.b64decode(sys.argv[1])

binary_string = ''.join(format(byte, '08b') for byte in decoded_bytes)


print( binary_string )
print( int(binary_string[154:160], 2) )





#device = tinytuya.OutletDevice(dev_id="bf06f140ee20807fdaalyq", local_key="K3Vv&|Jqqiq[VxP0",  address="192.168.0.191", version="3.3")

