
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
    return value.decode('ascii')
