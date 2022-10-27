from datetime import datetime, date, timedelta


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
