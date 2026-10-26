# Easun 8,2 / 10,2 kW — uživatelský manuál (pracovní přepis)

Zdroj: český překlad vyfotografovaného originálu, strany 5–40. Strany 1–4 nebyly
k dispozici, strana 14 (pokračování tabulky poruch baterie) je nečitelná.

Naše jednotka je **10,2 kW**. Potvrzeno z QPIRI: `ratedInputCurrent` /
`ratedOutputCurrent` = **44,3 A**, což je přesně hodnota, kterou manuál uvádí pro
10,2 kW model (8,2 kW má 35,6 A).

Manuál si na několika místech odporuje (momenty utažení, napěťová pásma).
Kde k tomu došlo, je to v textu poznamenáno. Rozhoduje štítek zařízení.

---

## 1. Nastavovací programy

Vstup: podržet ENTER 3 s. Výběr UP/DOWN, potvrzení ENTER, odchod ESC.

| Prog | Funkce | Rozsah / volby | Výchozí |
|---|---|---|---|
| 00 | Odchod / obnova | GOE odchod, GOH obnova jedním tlačítkem | GOE |
| 01 | Priorita napájení výstupu | USB (síť první) / SUB (solár první) / SBU (PV→baterie→síť) / nFS | SUB |
| 02 | Max. celkový nabíjecí proud AC + PV | 10–160 A | 100 A |
| 03 | Rozsah AC vstupu | APL 90–280 V / UPS 170–280 V | APL |
| 05 | Typ baterie | AGn / FLd / USE / LIb / LIB-485 | AGn |
| 06 | Auto-restart po přetížení | vyp / zap | vyp |
| 07 | Auto-restart po přehřátí | vyp / zap | vyp |
| 09 | Výstupní frekvence | 50 / 60 Hz | 50 Hz |
| 10 | Výstupní napětí | 220 / 230 / 240 V | 230 V |
| 11 | Max. nabíjecí proud ze sítě | 2, 10, 20 … 140 A (pevný seznam) | 80 A |
| 12 | Přechod na síť (SBU / Solar First) | **42–51 V, krok 1 V**; v LIB-485 SOC 10–50 % po 5 % | 46 V / 50 % |
| 13 | Návrat na baterii | FUL nebo 48–58 V; v LIB-485 SOC 30–100 % po 5 % | 54 V / 95 % |
| 16 | Priorita zdroje nabíjení | CSO solár první / SNU solár i síť / **OSO pouze solár** | SNU |
| 18 | Zvukový alarm | zap / vyp | zap |
| 19 | Auto-návrat LCD | po 1 min / zachovat | po 1 min |
| 20 | Podsvícení LCD | zap / vyp | zap |
| 22 | Pípnutí při výpadku primárního zdroje | zap / vyp | zap |
| 23 | Bypass při přetížení z baterie | vyp / zap (přepne do Line) | vyp |
| 25 | Záznam chybových kódů | zap / vyp | zap |
| 26 | Nabíjecí napětí CV (Bulk) | 48,0–61,0 V po 0,1 V (pro USE) | 56,4 V |
| 27 | Float — udržovací napětí | 48–61 V po 0,1 V (pro USE) | 54,0 V |
| 29 | Spodní odpojovací napětí | 40–48 V po 0,1 V; v LIB-485 SOC 5–30 % | 40 V / 20 % |
| 30 | Ekvalizace | vyp / zap (jen FLd a USE) | vyp |
| 31 | Ekvalizační napětí | 48–61 V po 0,1 V | 58,4 V |
| 33 | Doba ekvalizace | 5–900 min po 5 min | 60 min |
| 34 | Časový limit ekvalizace | 5–900 min po 5 min | 120 min |
| 35 | Interval ekvalizace | 0–90 dní | 30 dní |
| 36 | Spustit ekvalizaci ihned | AEn / AdS (jen když prog. 30 zapnut) | AdS |
| 37 | Režim připojení k síti | **OFF ostrovní / HYd hybridní s přetoky do sítě** | OFF |
| 38 | Proud při dodávce do sítě | krok 2 A | — |
| 39 | Světelný vzor LED | LOF / LON | LON |
| 41 | Dvojitý výstup | L2F vyp / L2O zap | L2F |
| 42 | Napěťový práh dvojitého výstupu | 40,0–52,0 V po 0,1 V | 44,0 V |
| 42 | Procentní práh dvojitého výstupu | 5–85 % | 55 % |
| 43 | Protokol BMS | PYL (Pylontech) / PAC (PACE) | PYL |
| 44 | Zpožděný přístup k síti | DIS / ENA | ENA |
| 45 | Max. zatížení druhého výstupu | 20–70 % jmenovitého výkonu | — |

> ⚠ **Program 37 (HYd) nikdy nezapínat.** Připouští dodávku do sítě. Nemáme
> ověřenou ochranu proti ostrovnímu provozu ani souhlas distributora.

> ⚠ **Ekvalizaci (prog. 30, 36) nikdy nezapínat.** Je určená pro olověné
> baterie. Na NMC ani LFP se nepoužívá — balancování řídí BMS článků.

---

## 2. Technické parametry

### Střídač

| Parametr | 8,2 kW | 10,2 kW |
|---|---|---|
| Jmenovitý výkon | 8 200 W | 10 200 W |
| Max. účinnost (DC/AC) | 93 % | 93 % |
| Přetížení | 3 s při ≥150 %, 5 s při 101–150 % | stejné |
| Špičkový výkon | 2× jmenovitý po 5 s | 2× jmenovitý po 5 s |
| Jmenovité DC napětí | 48 V | 48 V |
| Napětí studeného startu | 46,0 V | 46,0 V |
| **Spotřeba bez zátěže** | **70 W** | **75 W** |
| Odpojení DC při zátěži <50 % / ≥50 % | 41,0 / 40,0 V | 41,0 / 40,0 V |
| Odpojení při vysokém DC | 63 V | 63 V |
| Jmenovitý výstupní proud | 35,6 A | **44,3 A** |

### Fotovoltaika — **dva samostatné kanály**

| Parametr | Hodnota |
|---|---|
| PV1 max. výkon | 5 400 W |
| PV2 max. výkon | 5 400 W |
| Max. proud PV1 / PV2 | **18 A na kanál** |
| Jmenovité PV napětí | 360 V DC |
| MPPT rozsah | 90–450 V DC |
| Maximální PV Voc | 500 V DC |
| Max. nabíjecí proud AC + PV | 160 A |
| Max. AC nabíjecí proud | 140 A |

LCD přepíná obrazovky zvlášť pro PV1 a PV2 — napětí, proud **i energii v kWh**
(manuál str. 27: „energie PV2 1,434 kWh" vedle „energie PV 0,434 kWh").
Firmware tedy oba trackery vede odděleně. Viz oddíl 5.

### Síťový režim (Line)

| Parametr | Hodnota |
|---|---|
| Jmenovité napětí | 230 V AC |
| Dolní mez odpojení / návratu | 170 ± 7 / 180 ± 7 V (UPS); 90 ± 7 / 100 ± 7 V (APL) |
| Horní mez odpojení / návratu | 280 ± 7 / 270 ± 7 V |
| Frekvence — dolní / horní mez | 40 ± 1 / 65 ± 1 Hz |
| Přepínací čas | 10 ms (UPS) / 20 ms (APL) |
| Účinnost v režimu Line | > 95 % |

Derating: od cca 170 V vstupního AC klesá dostupný výkon, při cca 90 V je na 50 %.

### Dvojitý výstup

| Parametr | 8,2 kW | 10,2 kW |
|---|---|---|
| Rozsah druhého výstupu | 1 640–5 740 W | 2 040–7 140 W |
| Vypínací napětí hlavního výstupu | 52 V DC | 52 V DC |
| Návratové napětí hlavního výstupu | 54 V DC | 54 V DC |

---

## 3. Komunikace a BMS

Konektor RJ45 — **není to ethernetový pinout**:

| Pin | Funkce |
|---|---|
| 1 | RS485B |
| 2 | RS485A |
| 3–6 | nepoužito |
| 7 | RS485A |
| 8 | RS485B |

Rychlost pro bateriovou komunikaci 9 600 Bd.

Při `prog. 05 = LIB-485` a `prog. 43 = PYL/PAC`:

- programy 12, 13 a 29 přejdou z napětí na **procenta SOC**,
- maximální nabíjecí proud **nelze ručně měnit**, řídí ho BMS,
- **při ztrátě komunikace měnič odpojí výstup**.

### Výstražné kódy baterie (z BMS)

| Kód | Význam | | Kód | Význam |
|---|---|---|---|---|
| 21 | Přepětí článku | | 28 | Přehřátí článku při vybíjení |
| 22 | Podpětí článku | | 29 | Nízká teplota článku při nabíjení |
| 23 | Přepětí packu | | 30 | Nízká teplota článku při vybíjení |
| 24 | Podpětí packu | | 34 | Nízká kapacita baterie |
| 25 | Nadproud při nabíjení | | 44 | Rozdílné napětí článků |
| 26 | Nadproud při vybíjení | | 45 | Rozdílné teploty článků |
| 27 | Přehřátí článku při nabíjení | | 46 | Alarm interní komunikace |

---

## 4. Poruchy a výstrahy měniče

### Chybové kódy (FAULT svítí)

| Kód | Porucha | | Kód | Porucha |
|---|---|---|---|---|
| 01 | Ventilátor zablokován (střídač vypnut) | | 51 | Nadproud / proudová špička |
| 02 | Přehřátí | | 52 | Nízké napětí DC meziobvodu |
| 03 | Příliš vysoké napětí baterie | | 53 | Selhání měkkého startu střídače |
| 04 | Příliš nízké napětí baterie | | 55 | Vysoká DC složka na AC výstupu |
| 05 | Zkrat na výstupu / přehřátí prvků | | 57 | Porucha snímače proudu |
| 06 | Příliš vysoké výstupní napětí | | 58 | Příliš nízké výstupní napětí |
| 07 | Přetížení nad povolenou dobu | | 59 | Překročení PV napětí |
| 08 | Vysoké napětí DC meziobvodu | | | |
| 09 | Selhání měkkého startu meziobvodu | | | |

### Výstrahy (FAULT bliká)

| Kód | Událost | Zvuk |
|---|---|---|
| 01 | Ventilátor zablokován (měnič zapnut) | 3× / s |
| 03 | Baterie je přebíjená | 1× / s |
| 04 | Nízké napětí baterie | 1× / s |
| 07 | Přetížení | 1× / 0,5 s |
| 10 | Omezení výstupního výkonu | 2× / 3 s |
| 15 | Nízký solární výkon | 2× / 3 s |
| EQ | Probíhá ekvalizace | — |
| bP | Baterie není připojena | — |

---

## 5. Co z manuálu plyne pro naši instalaci

Porovnání manuálu proti skutečnému stavu (QPIRI snapshot, 2026-10-26).

### Potvrzeno

| Co | Hodnota u nás | Manuál |
|---|---|---|
| Model | `ratedOutputCurrent` 44,3 A | 10,2 kW |
| Max. nabíjecí proud | `solarMaxChargingCurrent` 160 | prog. 02 strop 160 A — jedeme na maximu |
| Přechod na síť | `batteryVoltageMainsSwitchingPoint` 49,0 V | prog. 12, rozsah 42–51 V |
| Návrat na baterii | `batteryVoltageHighEndInverterSwitching` 51 V | prog. 13, rozsah 48–58 V |
| Priorita výstupu | `loadPowerSourcePriority` SBU | prog. 01 |
| Typ baterie | `batteryType` USE | prog. 05 |
| Rozsah AC vstupu | `inputRange` ALP | prog. 03, 90–280 V |

### Nálezy

**a) Krok programu 12 je 1 V, takže 49,5 V nejde nastavit.**
Dohodnutý kompromis 49,5 V je pod rozlišením parametru. Reálná volba je 49
nebo 50 V. Aktuálně je nastaveno 49 V.

**b) Nabíjení ze sítě se dá vypnout pořádně — program 16 na OSO.**
Teď máme `mainsMaxChargingCurrent` **2 A**, což je nejnižší položka seznamu
programu 11; nulu ten program nenabízí, proto síťové nabíjení jen škrtíme,
nevypínáme. Program 16 má volbu **OSO = „baterii nabíjí pouze PV bez ohledu na
dostupnost sítě"**, což je přesně to, co chceme. Teď je `chargingSourcePriority`
na **CSO** (solár první, síť při nedostupném PV).

**c) Auto-restart je vypnutý a to nás stálo výjezd.**
Programy **06** (restart po přetížení) a **07** (restart po přehřátí) jsou
z výroby vypnuté. Po přetížení měnič zůstane ve FAULT a čeká na ruční zásah.
Při přetěžování, které u nás nastalo, by zapnutí znamenalo samočinné zotavení.

**d) Program 23 — bypass při přetížení z baterie.**
Při zapnutí měnič při přetížení v bateriovém režimu přepne na síť místo FAULT.
Pozor: u nás by tím zátěž spadla na jediný 16A jistič.

**e) Spotřeba naprázdno je 75 W.**
Tím je zodpovězená otevřená otázka u dopočtu PV z bilance — idle člen měniče
není odhad, je to katalogová hodnota.

**f) QPIRI nemůže jmenovitý výkon vrátit správně.**
Snapshot hlásí `ratedAcOutputApparentPower` a `ratedAcOutputActivePower`
= **200,0**, zatímco jednotka má 10 200 W. Pole HHHH/IIII protokolu PI30 jsou
čtyřmístná, takže 10200 se do nich nevejde a přeteče na „0200". Není to chyba
našeho parseru ani měniče — je to strop protokolu. *(Odvozeno z aritmetiky,
nepotvrzeno čtením syrového rámce; ověřit, až bude démon příště zastavený.)*

**g) PV2 existuje v firmwaru odděleně — stojí za druhý pokus.**
`probe_commands.py` nenašel příkaz, který by druhý tracker vrátil. Manuál ale
dokládá, že LCD zobrazuje PV1 i PV2 zvlášť **včetně samostatných počítadel kWh**.
Data tedy uvnitř jsou. Druhý sweep má smysl zaměřit na energetické příkazy
(QET / QEY / QLT s indexem trackeru). **Nutně za světla** — v noci je každé PV
pole nulové a rámec se dvěma stringy vypadá stejně jako rámec s jedním.

**h) LIB-485 je lákavé, ale pro nás rizikové.**
Režim by měniči dodal skutečné SOC z BMS místo napěťového odhadu. Náš JK BMS
má RS485 port, který podle typu umí Pylontech protokol. Jenže manuál říká, že
při ztrátě komunikace **měnič odpojí výstup** — a máme šest packů, z nichž by
mluvil jen jeden. Nezavádět bez samostatného rozmyslu.

### Limity, které je dobré mít na očích

- **18 A na PV kanál.** Při paralelním řazení větví na jeden vstup se limit
  vztahuje na každý vstup zvlášť.
- **500 V Voc** se počítá pro nejnižší návrhovou teplotu, ne pro teplotu v létě.
- **Odpojení při vysokém DC 63 V**, návrat 62 V.
- Protiprachový filtr se má podle manuálu čistit **jednou měsíčně**.
