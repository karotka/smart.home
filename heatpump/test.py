import os
import sys
import tinytuya
import json

import tinytuya

# Zadejte své přístupové údaje
DEVICE_ID = 'vaše_device_id'
DEVICE_KEY = 'vaše_device_key'
DEVICE_IP = 'IP_adresa_zařízení'

device = tinytuya.OutletDevice(dev_id="bf06f140ee20807fdaalyq", local_key="K3Vv&|Jqqiq[VxP0",  address="192.168.0.191", version="3.3")

payload = device.generate_payload(tinytuya.DP_QUERY)

response = device.send(payload)

#response = device.set_status(payload)
print("Odpověď zařízení:", response)

# Vytvoření objektu pro zařízení
#device = tinytuya.OutletDevice(DEVICE_ID, DEVICE_IP, DEVICE_KEY)

# Připojení k zařízení
#device.set_socketPersistent(True)

# Získání stavu zařízení

#dps_payload = {
#    'dps': {
#        '5': 'cool'  # Změňte '5' na 'cool'
#    }
#}

# Odeslání příkazu k nastavení parametru
#response = device.set_status(dps_payload)
#print("Odpověď zařízení:", response)

status = device.status()
print("Stav zařízení:", status)

# Zapnutí zařízení
#device.turn_on()
#print("Zařízení zapnuto.")

# Vypnutí zařízení
#device.turn_off()
#print("Zařízení vypnuto.")

#d = d1.status()["dps"]
#print (d)

