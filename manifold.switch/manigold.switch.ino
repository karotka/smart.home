/**
 * curl -v "http://192.168.x.x/0101000111"
 * GET http://192.168.x.x/0101000111 HTTP1.1
 * avrdude -P usb -p m328p -c usbtiny -U flash:w:build-uno/manifold.switch.hex
 */
#include <UIPEthernet.h>
#include "config.h"
#include <debugutil.h>

#include <SPI.h>
#include <Wire.h>
#include "SSD1306Ascii.h"
#include "SSD1306AsciiWire.h"

//#define SCREEN_WIDTH 128 // OLED display width, in pixels
//#define SCREEN_HEIGHT 32 // OLED display height, in pixels

// Declaration for an SSD1306 display connected to I2C (SDA, SCL pins)
// The pins for I2C are defined by the Wire-library.
// On an arduino UNO:       A4(SDA), A5(SCL)
// On an arduino MEGA 2560: 20(SDA), 21(SCL)
// On an arduino LEONARDO:   2(SDA),  3(SCL), ...
#define SCREEN_ADDRESS 0x3C ///< See datasheet for Address; 0x3D for 128x64, 0x3C for 128x32
//Adafruit_SSD1306 display = Adafruit_SSD1306(128, 32, &Wire);
SSD1306AsciiWire display;
EthernetServer server = EthernetServer(LISTENPORT);


int pins[9] = {3,4,5,6,7,8,9,15,14};
uint8_t pingServer[4] = {PINGSERVER};
unsigned long previousMillis = 0;
unsigned long interval = 10000; //20s


void(* resetFunct) (void) = 0;

void setup() {
    //Serial.begin(9600);
    Wire.begin();
    Wire.setClock(400000L);

    display.begin(&Adafruit128x64, SCREEN_ADDRESS);
    display.setFont(Adafruit5x7);
    display.clear();

    delay(1000); // Pause for 2 seconds

    uint8_t mac[6] = {MACADDRESS};
    uint8_t myIP[4] = {MYIPADDR};
    uint8_t myMASK[4] = {MYIPMASK};
    uint8_t myGW[4] = {MYGW};

    //             MAC  IP    DNS   GW    MASK
    Ethernet.begin(mac, myIP, myGW, myGW, myMASK);
    server.begin();

    display.setCursor(0, 0);
    display.print("IP:");
    display.setCursor(30, 0);
    display.print(Ethernet.localIP());

    display.setCursor(0, 2);
    display.print("Mask:");
    display.setCursor(30, 2);
    display.print(Ethernet.subnetMask());

    display.setCursor(0, 4);
    display.print("GW:");
    display.setCursor(30, 4);
    display.print(Ethernet.gatewayIP());

    for (int i = 0; i < 9; i++) {
        pinMode(pins[i], OUTPUT);
    }
}

void response(EthernetClient &client, String &data) {
    if (data.length() != 9) {
        client.println("HTTP/1.1 400 Bad Request");
    } else {

        String str;
        for (unsigned int i = 0; i < data.length(); i++) {
            if (data.c_str()[i] == '0') {
                digitalWrite(pins[i], LOW);
            } else {
                digitalWrite(pins[i], HIGH);
            }
            str = str + data.c_str()[i];
            if (i < data.length() - 1) {
                str = str + "|";
            }
        }

        display.setCursor(0, 7);
        display.setLetterSpacing(2);
        display.print(str);
        client.println("HTTP/1.1 200 OK");
        client.println("Content-Type: application/javascript");
    }
    client.println("Connection: close");
}

void loop() {

    EthernetClient client = server.available();

    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis > interval) {
        previousMillis = currentMillis;

        int res = client.connect(pingServer, 80);

        client.stop();
        if  (res == 0) {
            resetFunct();
        }

    } else {

        if (client) {

            boolean currentLineIsBlank = true;
            String request;

            while (client.available()) {

                //if () {

                    char c = client.read();

                    if (request.indexOf("HTTP/") == -1) {
                        request += c;
                    }

                    if (c == '\n' && currentLineIsBlank) {
                        String data = request.substring(5, 14);
                        data.trim();
                        response(client, data);
                        break;
                    }

                    if (c == '\n') {
                        // you're starting a new line
                        currentLineIsBlank = true;
                    } else if (c != '\r') {
                        // you've gotten a character on the current line
                        currentLineIsBlank = false;
                    }
                    // }
            }

            // give the web browser time to receive the data
            delay(10);

            // close the connection:
            client.stop();
        }
    }
}
