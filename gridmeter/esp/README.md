# gridmeter — KLEFR 6914 na WiFi

Čte elektroměr **KLEFR 6914** (přeznačkovaný Inepro PRO1-Mod) po RS485 a
publikuje ho na MQTT do `home/grid/meter/snapshot`.

Proč vůbec: na přívodu ze sítě žádný měřák nebyl, takže se odběr dopočítával
z energetické bilance (`zátěž + do baterky − panely`). To je přesné, dokud
měnič visí na síti, protože se výraz smrskne na změřenou zátěž — ale pořád je
to aritmetika. Tohle ji nahradí měřením z MID certifikovaného elektroměru.

## Proč ESP32 a ne ESP8266

Elektroměr jede z výroby na **9600 8E1** — sudá parita. Softwarový UART na
ESP8266 ani mini-UART na Raspberry Pi paritní bit neumí, takže na nich měřák
mlčí. ESP32 má hardwarový UART, kde je to jeden parametr.

## Zapojení

```
MAX485            ESP32
  RO      ->  GPIO16  (RX)
  DI      ->  GPIO17  (TX)
  DE + RE ->  GPIO4   (spojit dohromady)
  VCC     ->  3V3     (viz níže)
  GND     ->  GND
  A       ->  svorka 23 elektroměru
  B       ->  svorka 24 elektroměru
```

⚠ **MAX485 je 5V součástka a GPIO na ESP32 není 5V tolerantní.** Buď modul
napájej z 3V3 — mimo specifikaci, ale na 9600 baud a krátkém vedení to chodí
— nebo dej na `RO` dělič. Napájet z 5 V a vést `RO` přímo do ESP znamená
odejitý pin.

Na konce sběrnice patří **120 Ω** přes A/B. Bez terminace dává levný budič
občasné CRC chyby, které vypadají úplně stejně jako špatné nastavení linky.

Elektroměr musí být **napájený** (230 V na svorkách 1 a 4), jinak
nekomunikuje. Měřený obvod jím prochází: `L-IN` svorka 1, `L-OUT` svorka 3,
`N` svorky 4 a 6. Rozsah 5(45) A.

## Flashování

```
cp esp/secrets.h.example esp/secrets.h     # vyplnit, je v .gitignore
```

V `config.h` nastav **volnou IP** — dům už jednu kolizi má, na 192.168.0.17
sedí dvě čidla naráz a dostupné je vždy jen jedno.

## Když to nekomunikuje

Firmware si s tím poradí sám: pokud na nastavených parametrech nikdo
neodpoví, projede při startu všechny kombinace rychlosti a parity a použije
tu, která funguje. Výsledek posílá v payloadu jako pole `link`, takže
**desku zavřenou v rozvaděči diagnostikuješ z brokera**, ne s notebookem a
šroubovákem:

```
mosquitto_sub -h 192.168.0.224 -t 'home/grid/meter/snapshot' -C 1
```

`"link": "9600 8E1 addr 1"` znamená navázáno, `"nenavazano"` znamená, že
neodpověděl nikdo — pak jsou na řadě prohozené A/B (nejčastější a nic se tím
nerozbije), terminace, napájení měřáku a adresa mimo 1.

Pořadí slov u float32 se nenastavuje, firmware ho pozná podle toho, v kterém
vyjde registr napětí jako síťové napětí. Špatné pořadí dává hodnoty jako
3.7e-19, takže ten test není nijak jemný.

## Registry

Potvrzené je napětí a celková energie. Zbytek mapy je konvence rodiny PRO1,
ne něco přečtené z tohohle kusu — ověř `gridmeter/probe.py` proti reálnému
měřáku a případně oprav tabulku v `config.h`. Payload hlásí
`registers_ok`, kolik jich odpovědělo.

## Co zbývá

Až první zpráva dorazí na broker: navázat `mqtt_bridge.py` na Redis a zapsat
to do Influxu vedle dopočítaného `gridPowerIn`, ať je vidět, jak moc se
bilance trefovala.
