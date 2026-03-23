#!/usr/bin/python
"""
Invertor Monitor - Monitorování solárního invertoru přes RS232

Tento skript komunikuje se solárním invertorem (typ AXPERT/Voltronic) přes
sériový port RS232 a sbírá data o výrobě energie, stavu baterie a spotřebě.

ARCHITEKTURA:
=============
                                    ┌─────────────────┐
    ┌──────────┐    RS232           │   InfluxDB      │
    │ Invertor ├───────────────────►│  (time-series)  │
    │ (AXPERT) │    /dev/ttyUSB0    │                 │
    └──────────┘                    └────────┬────────┘
                                             │
    ┌──────────┐    RS232           ┌────────▼────────┐
    │ Invertor ├───────────────────►│     Redis       │
    │ (AXPERT) │    /dev/ttyUSB1    │   (live data)   │
    └──────────┘                    └─────────────────┘

DATOVÝ TOK:
===========
1. Skript se připojí k invertoru přes sériový port
2. Každou sekundu čte aktuální hodnoty (QPIGS příkaz)
3. Data se zapisují do InfluxDB pro historii
4. Aktuální hodnoty se ukládají do Redis pro webové rozhraní
5. Každou minutu se agregují data a upravuje nabíjecí proud

KOMUNIKAČNÍ PROTOKOL:
=====================
Invertor používá textový protokol s CRC16 kontrolním součtem:
- QID   - Dotaz na sériové číslo zařízení
- QMOD  - Dotaz na pracovní režim (Grid/Battery/Solar)
- QPIGS - Dotaz na aktuální hodnoty (napětí, proud, výkon, teplota...)
- QPIRI - Dotaz na nastavení invertoru
- MNCHGC - Nastavení nabíjecího proudu

SPUŠTĚNÍ:
=========
    python invertor.py first   # Pro první invertor (/dev/ttyUSB0)
    python invertor.py second  # Pro druhý invertor (/dev/ttyUSB1)

KONFIGURACE:
============
    conf/config.ini - IP adresy, porty, přihlašovací údaje

ZÁVISLOSTI:
===========
    pip install pyserial pandas influxdb redis

Autor: Smart Home Project
"""

import os
import sys
import serial
import time
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import datetime
import pickle
import redis
import configparser
import json
#import paho.mqtt.client as mqtt #import the client1
from influxdb import DataFrameClient
from crc16pure import crc16xmodem
from datetime import timedelta

# =============================================================================
# PŘÍKAZY PRO KOMUNIKACI S INVERTOREM (včetně CRC16 kontrolního součtu)
# =============================================================================
# Formát: PŘÍKAZ + CRC16 (2 bajty) + CR (0x0D)

QID   = b'QID\x18\x0b\r'      # Dotaz na sériové číslo zařízení
QMOD  = b'QMODI\xc1\r'        # Dotaz na pracovní režim (P=PowerOn, S=Standby, L=Line, B=Battery, F=Fault...)
QPIGS = b'QPIGS\xb7\xa9\r'    # Dotaz na aktuální provozní hodnoty (General Status Inquiry)
QPIRI = b'QPIRI\xf8T\r'       # Dotaz na nastavení/rating invertoru (Rating Information Inquiry)

# =============================================================================
# KONFIGURACE
# =============================================================================

# Pozice invertoru - určuje který sériový port použít
# Hodnoty: 'first' (/dev/ttyUSB0), 'second' (/dev/ttyUSB1), 'proto' (testovací)
position = sys.argv[1]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, "conf/config.ini"))

pidfile = "/tmp/invertor_%s.pid" % position
redisConn = None
broker_address="192.168.0.224"

#mqttCounter = 0

def createPid():

    pid = str(os.getpid())

    if os.path.isfile(pidfile):
        print("%s already exists, exiting" % pidfile)
        sys.exit()

    with open(pidfile, 'w') as f:
        f.write(pid)

createPid()


def createLog():
    """
    Creates a rotating log
    """
    handler = RotatingFileHandler(os.path.join(BASE_DIR, "log/invertor_%s_log" % position), backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s invertor [%(process)d]: %(message)s',
        '%b %d %H:%M:%S')
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

createLog()


def crc16(data):
    """
    Vypočítá CRC16 kontrolní součet pro příkaz invertoru.
    
    Args:
        data: Bajty příkazu pro výpočet CRC
        
    Returns:
        2 bajty CRC16 v big-endian formátu
    """
    return crc16xmodem(data).to_bytes(2, 'big')


class GeneralStatus:
    """
    Kontejner pro obecná nastavení invertoru získaná příkazem QPIRI.
    
    Atributy se dynamicky přidávají v metodě Invertor.getGeneralStatus():
    - gridVoltage: Jmenovité napětí sítě (V)
    - ratedInputCurrent: Jmenovitý vstupní proud (A)
    - ratedAcOutputVoltage: Jmenovité výstupní napětí AC (V)
    - ratedBatteryVoltage: Jmenovité napětí baterie (V)
    - batteryType: Typ baterie (AGM/FLD/USE)
    - solarMaxChargingCurrent: Max. nabíjecí proud ze solárů (A)
    - loadPowerSourcePriority: Priorita zdroje (UTL/SOL/SBU)
    - chargingSourcePriority: Priorita nabíjení (CUT/CSO/SUN/OSO)
    - parallelMode: Režim paralelního zapojení
    - ... a další
    """
    pass


class Invertor:
    """
    Hlavní třída pro komunikaci se solárním invertorem přes RS232.
    
    Invertor komunikuje pomocí textového protokolu. Každý příkaz obsahuje
    název příkazu, případné parametry, CRC16 kontrolní součet a CR znak.
    
    Podporované invertory:
    - AXPERT / Voltronic Power
    - MPP Solar
    - Podobné čínské invertory s RS232 rozhraním
    
    Příklad použití:
        inv = Invertor()           # Otevře sériový port
        inv.refreshData()          # Načte aktuální hodnoty
        print(inv.batteryVoltage)  # Napětí baterie
        print(inv.solarCurrent)    # Proud ze solárních panelů
    """

    def __init__(self):
        """
        Inicializuje invertor a otevře sériové připojení.
        
        Atributy - aktuální hodnoty (aktualizují se voláním refreshData()):
            deviceNumber: Identifikátor zařízení ('first', 'second', ...)
            gridVoltage: Napětí sítě (V)
            gridFreq: Frekvence sítě (Hz)
            outputVoltage: Výstupní napětí (V)
            outputFreq: Výstupní frekvence (Hz)
            outputPowerApparent: Zdánlivý výkon (VA)
            outputPowerActive: Činný výkon (W)
            loadPercent: Zatížení (%)
            busVoltage: Napětí na DC sběrnici (V)
            batteryVoltage: Napětí baterie (V)
            batteryCurrent: Nabíjecí proud baterie (A)
            batteryCapacity: Kapacita baterie (%)
            temperature: Teplota invertoru (°C)
            solarCurrent: Proud ze solárních panelů (A)
            solarVoltage: Napětí solárních panelů (V)
            batteryVoltageSCC: Napětí baterie ze SCC (V)
            batteryDischargeCurrent: Vybíjecí proud baterie (A)
            workingStatus: Pracovní režim (P/S/L/B/F/H)
        """
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
        self.workingStatus       = ""
        self.warning             = None
        self.gs = GeneralStatus()

        self._open()


    def _open(self):
        """
        Otevře sériový port pro komunikaci s invertorem.
        
        Port se vybírá podle globální proměnné 'position':
        - 'first' nebo 'proto' -> /dev/ttyUSB0
        - 'second' -> /dev/ttyUSB1
        
        Parametry sériové komunikace:
        - Baudrate: 2400
        - Parita: žádná
        - Stop bity: 1
        - Datové bity: 8
        """
        if position == 'first' or position == "proto":
            port     = '/dev/ttyUSB0'
        elif position == 'second':
            port     = '/dev/ttyUSB1'

        self.serial = serial.Serial(
            port     = port,
            baudrate = 2400,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            bytesize = serial.EIGHTBITS
        )
        logging.info("Open serial: <%s>" % self.serial)


    def reconnect(self):
        """
        Znovu naváže spojení s invertorem.
        
        Používá se při chybě komunikace. Zavře port, počká 3 sekundy
        a znovu otevře spojení.
        """
        if self.serial.isOpen():
            self.serial.close()
            time.sleep(2)
            self.serial.flushInput()
            self.serial.flushOutput()
            time.sleep(1)
        self._open()


    def call(self, length):
        """
        Přečte odpověď z invertoru.
        
        Čte bajt po bajtu dokud nenarazí na CR (0x0D).
        Odpověď začíná závorkou '(' a končí CRC + CR.
        
        Args:
            length: Očekávaná délka odpovědi (pro oříznutí)
            
        Returns:
            List hodnot oddělených mezerou
            
        Příklad odpovědi na QPIGS:
            "(230.0 50.0 230.0 50.0 0500 0400 010 380 48.50 010 100 0032 0.0 000.0 00.00 00000 00010000 00 00 00000 010"
        """
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
        """
        Načte aktuální provozní hodnoty z invertoru.
        
        Posílá dva příkazy:
        1. QMOD - Zjistí pracovní režim invertoru
        2. QPIGS - Získá všechny aktuální hodnoty
        
        Pracovní režimy (workingStatus):
        - P: Power on (zapínání)
        - S: Standby (pohotovost)
        - L: Line (napájení ze sítě)
        - B: Battery (napájení z baterie)
        - F: Fault (chyba)
        - H: Power saving (úsporný režim)
        
        QPIGS odpověď (117 znaků):
        Pozice | Hodnota                    | Jednotka
        -------|----------------------------|----------
        0      | Napětí sítě               | V
        1      | Frekvence sítě            | Hz
        2      | Výstupní napětí           | V
        3      | Výstupní frekvence        | Hz
        4      | Zdánlivý výkon            | VA
        5      | Činný výkon               | W
        6      | Zatížení                  | %
        7      | Napětí DC sběrnice        | V
        8      | Napětí baterie            | V
        9      | Nabíjecí proud            | A
        10     | Kapacita baterie          | %
        11     | Teplota                   | °C
        12     | Solární proud             | A
        13     | Solární napětí            | V
        14     | Napětí baterie SCC        | V
        15     | Vybíjecí proud            | A
        """
        # Určení čísla zařízení podle sériového portu
        if self.serial.port == "/dev/ttyUSB0":
            self.deviceNumber = 'first'
        elif self.serial.port == "/dev/ttyUSB1":
            self.deviceNumber = 'second'
        elif self.serial.port == "/dev/ttyUSB2":
            self.deviceNumber = 'third'
        elif self.serial.port == "/dev/ttyUSB3":
            self.deviceNumber = 'fourth'

        # Zjištění pracovního režimu
        self.serial.write(QMOD)
        data = self.call(2)
        self.workingStatus = data[0]

        # Načtení všech provozních hodnot
        self.serial.write(QPIGS)
        data = self.call(117)
        self.gridVoltage         = data[0]   # Napětí sítě (V)
        self.gridFreq            = data[1]   # Frekvence sítě (Hz)
        self.outputVoltage       = data[2]   # Výstupní napětí (V)
        self.outputFreq          = data[3]   # Výstupní frekvence (Hz)
        self.outputPowerApparent = data[4]   # Zdánlivý výkon (VA)
        self.outputPowerActive   = data[5]   # Činný výkon (W)
        self.loadPercent         = data[6]   # Zatížení (%)
        self.busVoltage          = data[7]   # DC bus napětí (V)
        self.batteryVoltage      = data[8]   # Napětí baterie (V)
        self.batteryCurrent      = data[9]   # Nabíjecí proud (A)
        self.batteryCapacity     = data[10]  # Kapacita baterie (%)
        self.temperature         = data[11]  # Teplota (°C)
        self.solarCurrent        = data[12]  # Solární proud (A)
        self.solarVoltage        = data[13]  # Solární napětí (V)
        self.batteryVoltageSCC   = data[14]  # Napětí baterie ze SCC (V)
        self.batteryDischargeCurrent = data[15]  # Vybíjecí proud (A)



    def to_dict(self):
        """
        Vrátí aktuální hodnoty invertoru jako slovník.
        
        Returns:
            dict: Slovník s hodnotami pro DataFrame
        """
        return {
            'deviceNumber': self.deviceNumber,
            'gridVoltage': float(self.gridVoltage),
            'gridFreq': float(self.gridFreq),
            'outputVoltage': float(self.outputVoltage),
            'outputFreq': float(self.outputFreq),
            'outputPowerApparent': float(self.outputPowerApparent),
            'outputPowerActive': float(self.outputPowerActive),
            'loadPercent': float(self.loadPercent),
            'busVoltage': float(self.busVoltage),
            'batteryVoltage': float(self.batteryVoltage),
            'batteryCurrent': float(self.batteryCurrent),
            'batteryCapacity': float(self.batteryCapacity),
            'temperature': float(self.temperature),
            'solarCurrent': float(self.solarCurrent),
            'solarVoltage': float(self.solarVoltage),
            'batteryVoltageSCC': float(self.batteryVoltageSCC),
            'batteryDischargeCurrent': float(self.batteryDischargeCurrent),
        }


    def set(self, command, value):
        """
        Odešle příkaz pro nastavení parametru invertoru.
        
        Sestaví příkaz ve formátu: PŘÍKAZ + HODNOTA + CRC16 + CR
        
        Args:
            command: Název příkazu (např. 'MNCHGC', 'MUCHGC', 'POP')
            value: Hodnota parametru (string)
            
        Returns:
            Odpověď invertoru (obvykle 'ACK' pro úspěch, 'NAK' pro chybu)
            
        Příklad:
            inv.set("MNCHGC", "0030")  # Nastaví max nabíjecí proud na 30A
        """
        crc = crc16(("%s%s" % (command, value)).encode(encoding = 'UTF-8'))
        com = ('%s%s' % (command, value)).encode(encoding = 'UTF-8')
        data = com + crc + b'\r' 
        ret = self.serial.write(data)
        return self.call(ret)


    def setChargeCurrent(self, batteryVoltage):
        """
        Automaticky nastaví nabíjecí proud podle napětí baterie.
        
        Implementuje adaptivní nabíjení - čím vyšší napětí baterie,
        tím nižší nabíjecí proud. Toto chrání baterii před přebíjením
        a prodlužuje její životnost.
        
        Tabulka nabíjecích proudů:
        ┌─────────────────┬──────────────────┐
        │ Napětí baterie  │ Nabíjecí proud   │
        ├─────────────────┼──────────────────┤
        │ > 58.0 V        │ 10 A (minimum)   │
        │ > 57.8 V        │ 20 A             │
        │ > 57.0 V        │ 40 A             │
        │ > 56.0 V        │ 50 A             │
        │ ≤ 56.0 V        │ 60 A (maximum)   │
        └─────────────────┴──────────────────┘
        
        Args:
            batteryVoltage: Aktuální napětí baterie (V)
            
        Note:
            Příkaz se odešle pouze pokud se hodnota liší od aktuální.
            Používá příkaz MNCHGC (Max Charging Current).
        """
        value = 60  # Výchozí maximální proud
        if batteryVoltage > 58:
            value = 10
        elif batteryVoltage > 57.8:
            value = 20
        elif batteryVoltage > 57:
            value = 40
        elif batteryVoltage > 56:
            value = 50

        # Odeslat příkaz pouze pokud se hodnota změnila
        if self.gs.solarMaxChargingCurrent != value:
            v = str(value).zfill(4)
            ret = self.set("MNCHGC", v)[0]
            logging.info(
                "Battery voltage is: %s. Setting charge value to: %s, %s" % (
                    batteryVoltage, value, ret))


    def getGeneralStatus(self):
        """
        Načte nastavení a parametry invertoru (příkaz QPIRI).
        
        QPIRI vrací kompletní konfiguraci invertoru včetně:
        - Jmenovitých hodnot (napětí, proudy, výkony)
        - Nastavení baterie (typ, napětí, nabíjecí proudy)
        - Priorit napájení a nabíjení
        - Režimu paralelního zapojení
        
        Returns:
            GeneralStatus: Objekt s načtenými parametry
            None: Při chybě komunikace
            
        Příklad použití:
            gs = inv.getGeneralStatus()
            print(gs.batteryType)        # 'AGM', 'FLD' nebo 'USE'
            print(gs.solarMaxChargingCurrent)  # Max proud ze solárů
        """
        self.serial.write(QPIRI)
        data = self.call(100)

        try:
            self.gs.gridVoltage = float(data[0])
        except (ValueError, IndexError) as e:
            logging.error("Invalid data received: <%s>, error: %s", data, e)
            self.reconnect()
            return None

        self.gs.ratedInputCurrent = float(data[1])
        self.gs.ratedAcOutputVoltage = float(data[2])
        self.gs.ratedAcOutputFrequency = float(data[3])
        self.gs.ratedOutputCurrent = float(data[4])
        self.gs.ratedAcOutputApparentPower = float(data[5])
        self.gs.ratedAcOutputActivePower = float(data[6])
        self.gs.ratedBatteryVoltage = float(data[7])
        self.gs.batteryVoltageMainsSwitchingPoint = float(data[8])
        self.gs.batteryVoltageShutdown  = float(data[9])
        self.gs.batteryVoltageFastCharge  = float(data[10])
        self.gs.batteryVoltageFloating  = float(data[11])

        bt = int(data[12])
        if bt == 0: self.gs.batteryType = 'AGM'
        elif bt == 1: self.gs.batteryType = 'FLD'
        else: self.gs.batteryType = 'USE'

        self.gs.mainsMaxChargingCurrent  = int(data[13])
        self.gs.solarMaxChargingCurrent = int(data[14])

        inputRange = int(data[15])
        if inputRange == 0:
            self.gs.inputRange = 'ALP' # AAPL model 90-280V (switching time 8-20mS)
        else:
            self.gs.inputRange = 'UPS' # UPS model 170-280 (switching time 5-15

        loadPowerSourcePriority = int(data[16])
        if loadPowerSourcePriority == 0:
            self.gs.loadPowerSourcePriority = 'UTL' # UTL model (Mains priority) default
        elif loadPowerSourcePriority == 1:
            self.gs.loadPowerSourcePriority = 'SOL' # SOL model (Solar priority)
        else:
            self.gs.loadPowerSourcePriority = 'SBU' # SBU model (S solar energy 1 Battery 2 Mains 3)

        chargingSourcePriority = int(data[17])
        if chargingSourcePriority == 0:   self.gs.chargingSourcePriority = 'CUT' # utility first
        elif chargingSourcePriority == 1: self.gs.chargingSourcePriority = 'CSO' # solar first
        elif chargingSourcePriority == 2: self.gs.chargingSourcePriority = 'SUN' # solar & utility
        else: self.gs.chargingSourcePriority = 'OSO' # only solar Solar charging only

        self.gs.canBeParalleledEuquipment = int(data[18])

        parallelMode = int(data[21])
        if parallelMode == 0: self.gs.parallelMode   = 'NP'  # No paralel
        elif parallelMode == 1: self.gs.parallelMode = 'SP'  # single phase
        elif parallelMode == 2: self.gs.parallelMode = '3P1'
        elif parallelMode == 3: self.gs.parallelMode = '3P2'
        elif parallelMode == 4: self.gs.parallelMode = '3P3'

        self.gs.batteryVoltageHighEndInverterSwitching = 48 + int(float(data[22]))

        solarWorkingConditionsParallel = int(data[23])
        if solarWorkingConditionsParallel == 0: self.gs.solarWorkingConditionsParallel = 'ONE'
        elif solarWorkingConditionsParallel == 1: self.gs.solarWorkingConditionsParallel = 'ALL'

        automaticAdjustmentSolarMaximumChargingPower = int(data[24])
        if automaticAdjustmentSolarMaximumChargingPower == 0:
            self.gs.automaticAdjustmentSolarMaximumChargingPower = 'ALOAD' # According to load
        elif automaticAdjustmentSolarMaximumChargingPower == 1:
            self.gs.automaticAdjustmentSolarMaximumChargingPower = 'BMAX' # Battery maximum

        return self.gs


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

# =============================================================================
# DATABÁZOVÉ FUNKCE
# =============================================================================

def getClient():
    """
    Vytvoří připojení k InfluxDB databázi.
    
    InfluxDB se používá pro ukládání časových řad - historická data
    o výrobě energie, napětí baterie, spotřebě atd.
    
    Returns:
        DataFrameClient: Klient pro práci s InfluxDB pomocí pandas DataFrames
        
    Note:
        Funkce se opakovaně pokouší o připojení dokud neuspěje.
        Mezi pokusy čeká 3 sekundy.
    """
    while True:
        try:
            return DataFrameClient('192.168.0.224', 8086, 'root', 'root', 'invertor')
        except Exception as e:
            logging.error(e, exc_info=True)
            time.sleep(3)


def getRedisClient():
    """
    Vytvoří nebo vrátí existující připojení k Redis.
    
    Redis se používá pro ukládání aktuálních hodnot pro webové
    rozhraní smart home - umožňuje rychlý přístup k live datům.
    
    Returns:
        redis.Redis: Připojení k Redis serveru
        None: Při chybě připojení
        
    Note:
        Využívá connection pooling - připojení se vytvoří jednou
        a pak se znovu používá.
    """
    global redisConn
    try:
        if redisConn is None:
            raise Exception("Not connected")
        redisConn.ping()
    except Exception:
        try:
            host = config["Redis"].get("host")
            port = int(config["Redis"].get("port"))
            redisConn = redis.Redis(host, port)
        except Exception as e:
            logging.error("Redis connection failed: %s", e)
            return None
    return redisConn


def writeToDb(df, dt):
    """
    Zapíše agregovaná data do InfluxDB (voláno 1x za minutu).
    
    Tato funkce se volá na konci každé minuty a provádí:
    1. Agregaci nasbíraných vzorků (průměr za minutu)
    2. Zápis do tabulky 'invertor' (historická data)
    3. Aktualizaci nabíjecího proudu podle napětí baterie
    4. Zápis stavu invertoru do 'invertor_status'
    5. Mazání starých záznamů (starších než 1 hodina)
    
    Args:
        df: DataFrame s nasbíranými vzorky za minutu
        dt: Časové razítko
        
    Returns:
        dict: Slovník s nastavením invertoru (GeneralStatus)
        
    Tabulky v InfluxDB:
        invertor:        Minutové průměry všech hodnot
        invertor_status: Aktuální nastavení invertoru
    """
    df = df.set_index(['deviceNumber'])
    df = df.groupby(["deviceNumber"]).mean()
    df = df.round(1)
    df = df.reset_index()

    df["time"] = dt
    df.set_index(['time'], inplace = True)
        
    client = getClient()
    client.write_points(df, 'invertor', protocol = 'line')
    logging.info("Send data ok time: %s" % (dt))

    # Aktualizace nabíjecího proudu podle napětí baterie
    batteryVoltage = df.iloc[0]["batteryVoltage"]
    gsDict = inv.getGeneralStatus().__dict__
    inv.setChargeCurrent(batteryVoltage)

    # Smazání starých záznamů stavu
    client.query("delete from invertor_status where time < now() -1h")

    # Zápis aktuálního stavu invertoru
    df1 = pd.DataFrame(gsDict, index=[0])
    df1["time"] = dt
    df1.set_index(['time'], inplace = True)
    client.write_points(df1, 'invertor_status', protocol = 'line')
    return gsDict


def writeDb(df, dt, dataDict):
    """
    Zapíše aktuální hodnoty pro live monitoring (voláno každou sekundu).
    
    Tato funkce zajišťuje real-time zobrazení dat ve webovém rozhraní:
    1. Zápis do 'invertor_actual' v InfluxDB
    2. Načtení denních součtů za posledních 24 hodin
    3. Uložení do Redis pro rychlý přístup z webu
    
    Args:
        df: DataFrame s aktuálními hodnotami
        dt: Časové razítko
        dataDict: Slovník s daty pro uložení do Redis
        
    Tabulky v InfluxDB:
        invertor_actual: Sekundové vzorky (maže se po 1 hodině)
        invertor_daily:  Denní agregace (čte se pro statistiky)
        
    Redis klíče:
        invertor_1: Serializovaný slovník s aktuálními hodnotami
    """
    df = df.set_index(['deviceNumber'])
    df = df.groupby(["deviceNumber"]).mean()
    df = df.round(1)
    df = df.reset_index()

    df["time"] = dt
    df.set_index(['time'], inplace = True)
        
    # Zápis aktuálních dat pro online monitoring
    client = getClient()
    client.write_points(df, 'invertor_actual', protocol = 'line')

    # Smazání starých záznamů (starších než 1 hodina)
    client.query("delete from invertor_actual where time < now() -1h")

    # Načtení součtů za posledních 24 hodin pro statistiky
    df = client.query("select sum(batteryPowerIn) as batteryPowerIn, sum(batteryPowerOut) as batteryPowerOut,  sum(outputPowerActive) as outputPowerActive, sum(outputPowerApparent) as outputPowerApparent, sum(solarPowerIn) as solarPowerIn from invertor_daily where time > now() - 24h")
    try:
        dataDict["last"] = df["invertor_daily"].iloc[0].to_dict()
    except Exception:
        dataDict["last"] = dict()

    # Uložení do Redis pro webové rozhraní smart home
    redisClient = getRedisClient()
    if redisClient:
        redisClient.set("invertor_1", pickle.dumps(dataDict))

    del dataDict["last"]

    logging.info("Send data to invertor actual ok time: %s" % (dt))


# =============================================================================
# HLAVNÍ SMYČKA PROGRAMU
# =============================================================================
#
# Program běží v nekonečné smyčce a provádí:
# 1. Každou sekundu: čte data z invertoru a zapisuje do 'invertor_actual'
# 2. Každou minutu: agreguje data a zapisuje do 'invertor'
#
# Diagram toku dat:
#
#   ┌─────────────┐     každou sekundu      ┌──────────────────┐
#   │  Invertor   ├────────────────────────►│ invertor_actual  │
#   │  (RS232)    │                         │ (InfluxDB)       │
#   └─────────────┘                         └──────────────────┘
#         │                                          │
#         │                                          ▼
#         │                                 ┌──────────────────┐
#         │                                 │     Redis        │
#         │                                 │ (live data web)  │
#         │                                 └──────────────────┘
#         │
#         │ sbírá vzorky
#         ▼
#   ┌─────────────┐     každou minutu       ┌──────────────────┐
#   │  DataFrame  ├────────────────────────►│    invertor      │
#   │  (vzorky)   │     (průměr)            │ (InfluxDB)       │
#   └─────────────┘                         └──────────────────┘
#

lastMinute = -1

try:
    # Načtení počátečního stavu invertoru
    gsDict = inv.getGeneralStatus().__dict__
    
    while True:
        # Získání aktuálního času
        dt = pd.to_datetime('today').now()
        minute = dt.minute
        
        # Načtení aktuálních hodnot z invertoru
        inv.refreshData()

        # Vytvoření DataFrame s aktuálními hodnotami
        df = pd.DataFrame([inv.to_dict()], columns=columns)

        # Sloučení aktuálních hodnot s nastavením invertoru
        gsDict.update(df.iloc[0].to_dict())
        gsDict["workingStatus"] = inv.workingStatus 

        # Zápis aktuálních hodnot (každou sekundu)
        writeDb(df, dt, gsDict)

        # Agregace dat po minutách
        if minute == lastMinute:
            # Stejná minuta - přidat vzorek k ostatním
            dfAll = pd.concat([dfAll, df], ignore_index=True)
        else:
            # Nová minuta - zapsat agregovaná data předchozí minuty
            if lastMinute != -1:
                gsDict = writeToDb(dfAll, dt)

            # Začít sbírat vzorky pro novou minutu
            dfAll = df

        lastMinute = minute

except Exception as e:
    logging.error("Exception occurred", exc_info = True)

finally:
    # Vždy smazat PID soubor při ukončení
    os.unlink(pidfile)


