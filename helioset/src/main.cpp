#include "debugutil.h"
#include "config.h"

#include <esp.config.h>
#include <WiFi.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>

#include "thermistor.h"
#include <NTPClient.h>
#include <WiFiUdp.h>


extern const GFXfont FreeMono9pt7b;

/* Touch IRQ Pin - interrupt enabled polling
 */
XPT2046_Touchscreen ts(T_CS);

/* WiFi and WebServer
 */
ConfigWifi_t   configWifi;
AsyncWebServer server(80);
ESPConfig      espConfig(&configWifi, &server);
WiFiUDP        ntpUDP;
NTPClient      timeClient(ntpUDP, NTP_SERVER, DAYLIGHT_OFFSET_SEC, UPDATE_INTERVAL);

/* TFT Display
 */
TFT_eSPI tft = TFT_eSPI(); 

bool wasTouched = true;
uint16_t timeCounter = 0;
uint16_t redrawCounter = 0;
int rowHeight = 30;
int navigPointer = 0;

/* Format date and time
 */
String formatDateTime() {
    // epoch time to date and time
    unsigned long epochTime = timeClient.getEpochTime();

    struct tm timeinfo;
    localtime_r((time_t*)&epochTime, &timeinfo);

    // format date and time
    char buffer[30];
    snprintf(buffer, sizeof(buffer), "%02d.%02d.%04d %02d:%02d:%02d",
             timeinfo.tm_mday, timeinfo.tm_mon + 1, timeinfo.tm_year + 1900,
             timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
    return String(buffer);
}

/* Draw navigation
 */
void drawNavig() {
    
    tft.fillScreen(ILI9341_BLACK);
    tft.drawFastHLine(0, 180, 320, COLOR_MENU);
    
    int arrowSize = 20;

    // arrow up
    int x = 33;
    int y = 220;
    tft.drawLine(x, y, x - arrowSize, y - arrowSize, COLOR_MENU);
    tft.drawLine(x, y, x + arrowSize, y - arrowSize, COLOR_MENU); 

    // arrow down
    x = 285;
    y = 202;
    tft.drawLine(x, y, x - arrowSize, y + arrowSize, COLOR_MENU);
    tft.drawLine(x, y, x + arrowSize, y + arrowSize, COLOR_MENU); 

    tft.setTextSize(2);
    tft.setFreeFont(&FreeMono9pt7b);
    tft.setCursor(90, 220);
    tft.println("SELECT");
}

/* Draw menu
 */
void drawMenu(int x) {
    tft.setTextSize(1);
    tft.setTextColor(ILI9341_WHITE);
    tft.fillRect(0, 20, 320, 160, ILI9341_BLACK);

    String textLines[] = {
        "Teplota kolektoru:",
        "Teplota zasobniku:",
        "Cerpadlo:",
        "Kolektor:",
        "Topna tyc:",
        "Max. teplota zasob.:",
        "Teplotni diference:"
    };
    
    // Počáteční vertikální pozice
    int yStart = 50;
    int lineSpacing = LINE_SPACING; // Mezera mezi řádky

    int j = 0;
    for (int i = x; i < x + 5; i++) {
        tft.setCursor(8, yStart + (j * lineSpacing));
        tft.print(textLines[i]);
        j++;
    }
}

void setup() {
    EEPROM.begin(EEPROM_SIZE);

    Serial.begin(115200);

    // LittleFS initialization
    if (!LittleFS.begin()) {
        Serial.println("Nelze inicializovat LittleFS");
        return;
    }

    // WiFi and WebServer from ESPConfig
    espConfig.begin();

    // TFT Display and Touchscreen
    tft.begin();
    tft.setRotation(1);
    tft.fillScreen(ILI9341_BLACK);
    ts.begin();
    ts.setRotation(3);

    // NTP Client
    timeClient.begin();
    timeClient.update();

    // Menu
    drawNavig();
    drawMenu(0);
}

/* Main loop
 */
void loop() {

    bool istouched = ts.touched();

    if (istouched) {
        TS_Point p = ts.getPoint();
        //tft.fillRect(0, 0, 320, 180, ILI9341_BLACK);

        // touch arrow up
        if (p.x > 0 && p.x < 75 && p.y > 180) {
            navigPointer++;
        } else
        // touch arow down
        if (p.x > 220 && p.y > 150) {
            navigPointer--;
        }
        drawMenu(constrain(navigPointer, 0, 2));

        tft.fillRect(0, 225, 320, 20, ILI9341_BLACK);
        tft.setTextSize(1); // Velikost textu
        tft.setCursor(10, 237); // Nastavit pozici kurzoru
        tft.print(
            "X:" + String(p.x) + " Y:" + String(p.y) + " Z:" + String(p.z) + " P:" + String(navigPointer));

        delay(200);
    }
    wasTouched = istouched;

    // 320x240
    tft.setTextSize(1); // Velikost textu

    /* update time
     */
    if (timeCounter == 0) {
        tft.fillRect(30, 2, 230, 18, ILI9341_BLACK);
        tft.setCursor(35, 15);
        tft.setTextColor(ILI9341_DARKGREY);
        tft.print(formatDateTime());
        timeCounter = 30;
    }
    timeCounter--;

    /* redraw menu
     */
    if (redrawCounter == 0) {
        tft.setTextColor(ILI9341_WHITE);

        for (int i = 5; i < 126; i = i + LINE_SPACING) {
            tft.fillRect(240, i + rowHeight, 50, 20, ILI9341_DARKGREY);
        }
        redrawCounter = 50;
    }
    redrawCounter--;
        
    delay(10);
}

