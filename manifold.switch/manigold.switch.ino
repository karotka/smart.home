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


SSD1306AsciiWire display;
EthernetServer server = EthernetServer(LISTENPORT);


int pins[9] = {3,4,5,6,7,8,9,15,14};
uint8_t pingServer[4] = {PINGSERVER};
unsigned long previousMillis = 0;
unsigned long interval = 20000; //20s


void(* resetFunct) (void) = 0;

void setup() {
    //Serial.begin(9600);

#ifdef SCREEN_ADDRESS

    Wire.begin();
    Wire.setClock(400000L);

    display.begin(&Adafruit128x64, SCREEN_ADDRESS);
    display.setFont(Adafruit5x7);
    display.clear();

    delay(1000); // Pause for 2 seconds

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
#endif

    uint8_t mac[6] = {MACADDRESS};
    uint8_t myIP[4] = {MYIPADDR};
    uint8_t myMASK[4] = {MYIPMASK};
    uint8_t myGW[4] = {MYGW};

    //             MAC  IP    DNS   GW    MASK
    Ethernet.begin(mac, myIP, myGW, myGW, myMASK);
    server.begin();

    for (int i = 0; i < 9; i++) {
        pinMode(pins[i], OUTPUT);
    }
}

void response(EthernetClient &client, String &data) {
    if (data.length() != 9) {
        client.println("HTTP/1.1 400 Bad Request");
        client.println("Connection: close");
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
#ifdef SCREEN_ADDRESS
        display.setCursor(0, 7);
        display.setLetterSpacing(2);
        display.print(str);
#endif

        client.println("HTTP/1.1 200 OK");
        client.println("Content-Type: application/javascript");
        client.println("Connection: close");
        client.println("");
        client.print("{\"v\":\"");
        client.print(data);
        client.println("\"}");
    }
}

void loop() {

    EthernetClient client = server.available();
    //Serial.println(client);

    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis > interval) {
        previousMillis = currentMillis;

        int res = client.connect(pingServer, 80);
        client.print("GET /ping?t=");
        client.println(currentMillis);
        client.println("Connection: close");

        if  (res == 0) {
            resetFunct();
        }
        client.stop();

    } else {

        if (client) {

            boolean currentLineIsBlank = true;
            String request;

            while (client.available()) {

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
            }

            // give the web browser time to receive the data
            delay(10);

            // close the connection:
            client.stop();
        }
    }
}
