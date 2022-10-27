import serial
import time
import logging
import pandas as pd
import datetime
from influxdb import DataFrameClient

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

Q1 = b'Q1\x1b\xfc\r'
QPI = b"\x51\x50\x49\x82\x61\x0D"

QID = b'QID\x18\x0b\r'
QPIGS = b'QPIGS\xb7\xa9\r'


class Invertor:

    def __init__(self):
        self.deviceNumber        = 0
        self.gridVoltage         = 0.0
        self.gridFreq            = 0.0
        self.outputVoltage       = 0.0
        self.outputFreq          = 0
        self.outputPowerApparent = 0
        self.outputPowerActive   = 0
        self.loadPercent         = 0.0
        self.busVoltage          = 0.0
        self.batteryVoltage      = 0.0
        self.batteryCurrent      = 0.0
        self.batteryCapacity     = 0
        self.temperature         = 0
        self.solarCurrent        = 0.0
        self.solarVoltage        = 0
        self.batteryVoltageSCC   = 0
        self.batteryDischargeCurrent = 0
        self.status              = None
        self.warning             = None

        self._open()


    def _open(self):
        self.serial = serial.Serial(
            port     = '/dev/ttyUSB0',
            baudrate = 2400,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            bytesize = serial.EIGHTBITS
        )


    def reconnect(self):
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(2)
        self._open()


    def call(self, length):
        data = list()
        while 1:
            line = self.serial.read(1)
            #print (line)
            data.append(line.decode('utf-8', 'ignore'))
            if ord(line) == 13:
                data = "".join(data)
                data = data[1:length].split(" ")
                #print(data)
                if not data[0]:
                    #print ("reconnect")
                    self.reconnect()
                break
        return data


    def refreshData(self):
        self.serial.write(QID)
        data = self.call(16)
        self.deviceNumber = data[0]


        self.serial.write(QPIGS)
        data = self.call(117)
        self.gridVoltage         = data[0]
        self.gridFreq            = data[1]
        self.outputVoltage       = data[2]
        self.outputFreq          = data[3]
        self.outputPowerApparent = data[4]
        self.outputPowerActive   = data[5]
        self.loadPercent         = data[6]
        self.busVoltage          = data[7]
        self.batteryVoltage      = data[8]
        self.batteryCurrent      = data[9]
        self.batteryCapacity     = data[10]
        self.temperature         = data[11]
        self.solarCurrent        = data[12]
        self.solarVoltage        = data[13]
        self.batteryVoltageSCC   = data[14]
        self.batteryDischargeCurrent = data[15]


inv = Invertor()

columns = [
    "deviceNumber",
    "gridVoltage",
    "gridFreq",
    "outputVoltage",
    "outputFreq",
    "outputPowerApparent",
    "outputPowerActive",
    "loadPercent",
    "busVoltage",
    "batteryVoltage",
    "batteryCurrent",
    "batteryCapacity",
    "temperature",
    "solarCurrent",
    "solarVoltage",
    "batteryVoltageSCC",
    "batteryDischargeCurrent",
]

def getClient():
    return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')

lastMinute = -1
while 1 :

    try:
        inv.refreshData()
    except Exception as e:
        logging.error("Exception occurred", exc_info = True)

    df = pd.DataFrame(data = [[
        inv.deviceNumber,
        float(inv.gridVoltage),
        float(inv.gridFreq),
        float(inv.outputVoltage),
        float(inv.outputFreq),
        float(inv.outputPowerApparent),
        float(inv.outputPowerActive),
        int(inv.loadPercent),
        float(inv.busVoltage),
        float(inv.batteryVoltage),
        float(inv.batteryCurrent),
        int(inv.batteryCapacity),
        int(inv.temperature),
        float(inv.solarCurrent),
        float(inv.solarVoltage),
        float(inv.batteryVoltageSCC),
        float(inv.batteryDischargeCurrent)]], columns = columns )

    df = df.astype({
        'gridVoltage':'float',
        'gridFreq':'float',
        'outputVoltage':'float',
        'outputFreq':'float',
        'outputPowerApparent':'float',
        'outputPowerActive':'float',
        'busVoltage':'float',
        'batteryVoltage':'float',
        'batteryCurrent':'float',
        'solarCurrent':'float',
        'solarVoltage':'float',
        'batteryVoltageSCC':'float',
        'batteryDischargeCurrent':'float'
    })

    minute = datetime.datetime.now().minute
    if minute == lastMinute:
        dfAll = dfAll.append(df)
        #print (dfAll)
    else:
        if lastMinute != -1:
            dfAll = dfAll.set_index(['deviceNumber'])
            dfAll = dfAll.groupby(["deviceNumber"]).mean()
            dfAll = dfAll.round(1)
            dfAll = dfAll.reset_index()

            dfAll["time"] = pd.to_datetime('today').now()
            dfAll.set_index(['time'], inplace = True)

            getClient().write_points(dfAll, 'invertor', protocol='line')

        dfAll = df

    lastMinute = datetime.datetime.now().minute
