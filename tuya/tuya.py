import os
import subprocess
import base64


result = subprocess.run(['./tuya.sh'], stdout=subprocess.PIPE)

string = result.stdout.decode('utf-8')
string = string.split(":")[1].strip()

bstring = ''.join(format(byte, '08b') for byte in base64.b64decode(string) )

print (
	string
)

print (
	#base64.b64decode(string)
	bstring
)

#print (result.stdout)



