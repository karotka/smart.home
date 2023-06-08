/**
 * curl -v "http://192.168.0.6/?p=0&v=0"
 * curl -v "http://192.168.0.6/?p=0"
 */
#include <SPI.h>
#include <UIPEthernet.h>
#include "config.h"
#include <debugutil.h>
#include "thermistor.h"
#include <Watchdog.h>

EthernetServer server = EthernetServer(LISTENPORT);
Watchdog watchdog;

int pins0[] = {16,4,7,9,15};
int pins1[] = {3,5,6,8,14};
int values0[] = {0,0,0,0,0};
int values1[] = {0,0,0,0,0};
//uint8_t pingServer[4] = {PINGSERVER};

unsigned long previousMillis = 0;
unsigned long interval = 1000; //1s

//void(* resetFunct) (void) = 0;

void setup() {

    watchdog.enable(Watchdog::TIMEOUT_2S);

    //Serial.begin(9600);
    uint8_t mac[6] = {MACADDRESS};
    uint8_t myIP[4] = {MYIPADDR};
    uint8_t myMASK[4] = {MYIPMASK};
    uint8_t myDNS[4] = {MYDNS};
    uint8_t myGW[4] = {MYGW};

    Ethernet.begin(mac, myIP, myDNS, myGW, myMASK);
    server.begin();

    SLOG("IP Address:");
    SLOGLN(Ethernet.localIP());

    for (int i = 0; i < 5; i++) {
        pinMode(pins0[i], OUTPUT);
    }
    for (int i = 0; i < 5; i++) {
        pinMode(pins1[i], OUTPUT);
    }
}

void response(EthernetClient &client, String &request) {

    int length = request.indexOf("HTTP");
    String qs(request.substring(6, length - 1));
    int amp = request.indexOf("&");
    int comp = request.indexOf("=");
    int pin = request.substring(comp + 1, amp).toInt();
    int value;

    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: application/json");
    client.println("Connection: close");
    client.println("");

    if (amp > 0) {

        value = request.substring(amp + 3, length - 1).toInt();

        digitalWrite(pins0[pin], value);
        digitalWrite(pins1[pin], !value);

        values0[pin] = value;
        values1[pin] = !value;

        delay(50);

        digitalWrite(pins0[pin], false);
        digitalWrite(pins1[pin], false);

    } else {

        value = values0[pin];
    }

    client.print("{\"v\":");
    client.print(value);
    client.println("}");

}

void loop() {

    // listen for incoming clients
    EthernetClient client = server.available();
    //Serial.println(currentMillis);

    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis > interval) {

        watchdog.reset();
        previousMillis = currentMillis;

        /*
        int res = client.connect(pingServer, 80);
        client.print("GET /ping?t=");
        client.println(currentMillis);
        client.println("Connection: close");

        if  (res == 0) {
            resetFunct();
        }
        client.stop();
        */

    } else {

        if (client) {

            boolean currentLineIsBlank = true;
            String request;

            while (client.available()) {

                char c = client.read();

                if (request.indexOf("HTTP/1.") == -1) {
                    request += c;
                }

                if (c == '\n' && currentLineIsBlank) {
                    SLOGLN(request);
                    response(client, request);
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
            SLOGLN("Client disconnected");
            watchdog.reset();
        }
    }
}
