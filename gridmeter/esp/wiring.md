# Zapojení — celé schéma

```
                            ROZVADEC                                 KRABICKA U BATERIE
  ┌─────────────────────────────────────────────┐        ┌──────────────────────────────────┐
  │                                             │        │                                  │
  │   sit L ──[ Tuya jistic ]──┐                │        │   bat +51V ──[PTC 100mA/60V]──┐  │
  │                            │                │        │                               │  │
  │                     ┌──────┴──────┐         │        │                        ┌──────┴──────┐
  │                     │  1   L-IN   │         │        │                        │ VIN+   DCE003│
  │                     │             │         │        │   bat GND ─────────────│ VIN-  5V 2A  │
  │                     │   KLEFR     │         │        │                        │ EN ─┘ (na VIN+)│
  │                     │    6914     │         │        │                        │ OUT+   OUT-  │
  │                     │             │         │        │                        └──┬──────┬───┘
  │                     │  3   L-OUT  │         │        │                        5V │      │ GND
  │        menic AC-in ─┤             │         │        │                           │      │
  │                     │  4   N      │         │        │              220uF/16V ═══╪══════╡
  │                     │  6   N      │         │        │                           │      │
  │                     │             │         │        │                      ┌────┴──────┴────┐
  │                     │ 23  A ──────┼─┐       │        │                      │ VIN        GND │
  │                     │ 24  B ──────┼─┼─┐     │        │                      │                │
  │                     └──────┬──────┘ │ │     │        │                      │    ESP32       │
  │                     120R ══╧════════╪═╡     │        │                      │   DevKitC      │
  │                                     │ │     │        │                      │                │
  └─────────────────────────────────────┼─┼─────┘        │        100uF ═══╤════┤ 3V3            │
                                        │ │              │        100nF ═══╛    │                │
                 kroucena dvojlinka  A  │ │  B           │                      │ GPIO16 (RX)    │
                 (stineni na jedne      │ │              │                      │ GPIO17 (TX)    │
                  strane, nebo bez)     │ │              │                      │ GPIO4  (DE/RE) │
                                        │ │              │                      └──┬───┬───┬─────┘
                                        │ │              │                         │   │   │
                                        │ │              │   ┌─────────────────┐   │   │   │
                                        │ └──────────────┼───┤ B            RO ├───┘   │   │
                                        └────────────────┼───┤ A            DI ├───────┘   │
                                                         │   │              DE ├───────────┤
                                                         │   │              RE ├───────────┘
                                                         │   │ VCC ── 3V3      │
                                                         │   │ GND ── GND      │
                                                         │   │   MAX485 modul  │
                                                         │   │  (120R uz na nem)│
                                                         │   └─────────────────┘
                                                         └──────────────────────────────────┘
```

## Co je kde a proč

**Elektroměr se vkládá sériově do přívodu ze sítě k měniči**, tedy za Tuya
jistič a před AC vstup měniče. Ne na výstup měniče — tam by měřil spotřebu
domu, a tu už máme z `outputPowerActive`.

⚠ Svorky 1/3/4/6 jsou síťová strana 45 A. Čísla jsou odečtená ze štítku na
fotce; **než budeš pájet, ověř si je proti manuálu konkrétního kusu.**

**Terminaci na straně ESP už nemusíš řešit** — na tvém modulu je osazená.
Na fotce je rezistor `121`, což je 120 Ω, a dvojice `203` = 20 kΩ jsou
klidové předpětí sběrnice. Takže přidáváš jen **120 Ω přes svorky 23/24**
přímo na měřáku, tedy na druhém konci vedení.

**Mezi rozvaděčem a ESP veď kroucenou dvojlinku, jen `A` a `B`.** Žádnou
zem: DCE003 je neizolovaný, takže zem ESP sedí na mínusu baterie, a
propojením zemí bys mezi bateriovou sběrnicí a rozvaděčem udělal smyčku.

**Napájení z baterie, ne ze sítě.** Má to jeden vedlejší efekt, který v
rozvaděči oceníš: modul přežije shozený jistič. Elektroměr tím ztratí 230 V
a přestane odpovídat, ale ESP dál publikuje s `registers_ok: 0`. Shozený
jistič tak poznáš od chcíplé desky — což při napájení ze stejné fáze, kterou
měříš, nejde.

## Kondenzátory

| kde | hodnota | proč |
|-----|---------|------|
| 5 V, mezi `VIN` a `GND` | 220 µF / 16 V | WiFi špičky na delším přívodu |
| 3,3 V, mezi `3V3` a `GND`, co nejblíž modulu | 100 µF / 10 V | AMS1117 má mizernou odezvu na skok |
| tamtéž, paralelně | 100 nF keramika | vysoké frekvence |

Napětí na kondenzátoru je jeho maximum, ne provozní hodnota — na 5V větev
proto 16 V, ne 5 V.

Podpěťové resety u ESP32 většinou nedělá 5V větev, ale ta 3,3V za
regulátorem. Bez toho stokilového kondenzátoru se to projeví jako záhadné
restarty a budeš je hledat v softwaru.

## Pozor na desku

`GPIO16` a `GPIO17` jsou volné na modulech **ESP32-WROOM**. Na **WROVER**
(ten s PSRAM) jsou obsazené pamětí a nebudou fungovat — tam zvol třeba
`GPIO25` / `GPIO26` / `GPIO27` a oprav `RS485_*_PIN` v `config.h`.

Pokud máš holý modul bez desky (bez regulátoru a bez `VIN`), potřebuješ
DCE003 ve variantě 3,3 V, nebo za něj LDO. `VIN` = 5 V platí jen pro
vývojové desky jako DevKitC nebo NodeMCU-32S.

## Proud

ESP32 bere ve špičce při vysílání kolem 350 mA z 5 V, tedy asi 36 mA z
bateriové sběrnice při 51 V. PTC 100 mA / 200 mA @ 60 V z BMS modulů tím
projde s rezervou — je to ten samý díl.
