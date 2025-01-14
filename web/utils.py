from datetime import datetime, date, timedelta
import base64


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


