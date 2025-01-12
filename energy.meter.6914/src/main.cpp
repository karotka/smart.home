#include "debugutil.h"
#include <SoftwareSerial.h>
#include <ModbusRTUMaster.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Fonts/FreeMono9pt7b.h>



//#define RX_PIN D3        // RX pin (GPIO 13)
//#define TX_PIN D6        // TX pin (GPIO 15)
#define DE_RE_PIN D0     // DE/RE pin pro RS-485
#define SCREEN_WIDTH 128     // Display width
#define SCREEN_HEIGHT 64     // Display height
#define SCREEN_ADDRESS 0x3C  // Display address
#define SCREEN_CONTRAST 0x8F // Initialize contrast value


/* WiFiServer server(LISTENPORT);
 */
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

//SoftwareSerial mySerial(RX_PIN, TX_PIN); // Vytvoření SoftwareSerial objektu
ModbusRTUMaster node(Serial, DE_RE_PIN);                     // Vytvoření ModbusMaster instance

/* Display setup
 */
void displaySetup(Adafruit_SSD1306 &display) {
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(SCREEN_CONTRAST);

    display.clearDisplay(); // Display delete all
    display.setFont(&FreeMono9pt7b);
    //display.setFont(NULL);
    display.setTextColor(SSD1306_WHITE);
    display.display(); 
}


void setup() {
    /* Display Init
     */
    if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
        SLOGLN(F("Cannot inicialized OLED!"));
        while (true); // Stop
    }
    displaySetup(display);


    Serial.begin(9600, SERIAL_8E1);
    //mySerial.begin(4800);                // Spuštění SoftwareSerial ve 9600 baudů
    pinMode(DE_RE_PIN, OUTPUT);          // Nastavení DE/RE pinu jako výstup
    digitalWrite(DE_RE_PIN, LOW);        // Výchozí režim příjmu

    node.begin(4800, Serial);             // Inicializace Modbus RTU s ID 1
    node.setTimeout(2000);        // Nastavení timeoutu na 1 sekundu
    //Serial.println("Modbus RTU Master Initialized");
}


/* Display rerender
 */
void displayPrint(String value) {
    
    display.setTextSize(1);

    display.setCursor(0, 12);
    //display.fillRect(64, 0, 64, 14, BLACK);
    display.println(value);
    display.display(); 

}

void loop() {
    display.clearDisplay(); // Display delete all

    static uint32_t lastMillis = 0;

    if (millis() - lastMillis > 250) { // Číst každé 2 sekundy
        lastMillis = millis();


        //displayPrint("Reading register");

        // Čtení holding registru
        uint16_t buf[1];
        uint8_t result = node.readHoldingRegisters(1, 4004, buf, 1); // Načtení registru s adresou 5002


        if (result == MODBUS_RTU_MASTER_SUCCESS) {
            // Přečteno úspěšně
            //uint16_t len = 0;
            char inData[20];
            unsigned long timeout = millis() + 1000;
            uint8_t inIndex = 0;
            while ( ((int32_t)(millis() - timeout) < 0) && (inIndex < (sizeof(inData)/sizeof(inData[0])))) {
                if (Serial1.available() > 0) {
                // read the incoming byte:
                    inData[inIndex] = Serial.read();
                    inIndex++;
                }
            }
            displayPrint(">" + String(inData) ); // Tisk hodnoty registru
            //
        } else {
            // Ošetření chyby
            displayPrint("Error reading register: " + String(result)); // Tisk chybového kódu
        }

    }



    //node.task(); // Udržujte aktivní úlohu Modbus RTU
}
