import sys
import base64
import tinytuya


decoded_bytes = base64.b64decode(sys.argv[1])

print (decoded_bytes)
print (base64.b64encode(decoded_bytes))

binary_string = ''.join(format(byte, '08b') for byte in decoded_bytes)

print (binary_string, "->", int(binary_string[154:160], 2))

