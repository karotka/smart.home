#include "debugutil.h"
#include "config.h"

#include <Wire.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <PubSubClient.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Fonts/FreeMonoBold9pt7b.h>

#include "thermistor.h"
#include <esp.wifi.setting.h>
#include <Ticker.h>


ConfigWifi_t configWifi;
ESP8266WebServer server(80);
ESPConfig setting(&configWifi, &server);
Ticker timer0;


/* WiFiServer server(LISTENPORT);
 */
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

/* Use WiFiClient class to create TCP connections
 */
WiFiClient client; 

/* MQTT client
 */
PubSubClient mqttClient(client);

/* Thermistors
 */
Thermistor t0(0);
Thermistor t1(1);
Thermistor t2(2);

/* Global Variables
 */
volatile int te0 = 0;
volatile int te1 = 0;
volatile int te2 = 0;
volatile int pwr = 0;
volatile int clientCounter = 0;
volatile int mqttClientCounter = 0;
volatile int displayCounter = 0; 

volatile int ledCounter = 0; 
volatile int ledBuildin = 0;

/* Setup
 */
void setup() {
    
    Serial.begin(9600);

    /* Start filesystem
     */
    LittleFS.begin();

    /* EEPROM for store wifi configuration
     */
    EEPROM.begin(EEPROM_SIZE);
    
    /* Register methods for IP settings
     */
    uint16_t lastAddress = setting.begin();
    SLOGF("Last EEPROM address = %d", lastAddress);

    /* Start server
     */
    server.begin();

    /* pins for multiplexer
     */
    pinMode(MUXPIN_A, OUTPUT);
    pinMode(MUXPIN_B, OUTPUT);
    pinMode(MUXPIN_C, OUTPUT);

    /* Display Init
     */
    if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
        SLOGLN(F("Cannot inicialized OLED!"));
        while (true); // Stop
    }

    /* Display setup will print main menu
     */
    displaySetup(display);

    pinMode(LED_BUILTIN, OUTPUT);

    timer0.attach(0.1, ledFlash);

    SLOGF("CpuFreqMHz: %u MHz\n", ESP.getCpuFreqMHz());
    SLOGF("Last restart reason <%s>", ESP.getResetReason().c_str());

    /* Check if we are in AP mode
     * if not return and finish setup
     */
    CONNECTED();

    connectMqtt();
}

/* MQTT server connection
 */
void connectMqtt() {
    if (!configWifi.mqttServer) {
        SLOGLN("MQTT server not set");
        return;
    }

    if (!mqttClient.connected()) {
        mqttClient.setServer(configWifi.mqttServer.c_str(), static_cast<uint16_t>(configWifi.mqttPort.toInt()));

        if (mqttClient.connect("ESP8266Client", configWifi.mqttUser.c_str(), configWifi.mqttPassword.c_str())) {
            SLOGLN("MQTT broker connected");
        } else {
            SLOG("Cannot connect to MQTT broker, error: ");
            SLOGLN(mqttClient.state());
        }
    }
}

/* Led flash
 */
void ledFlash() {
    int interval;

    if (pwr > 80) {
        interval = 3;
    } else if (pwr > 60) {
        interval = 4;
    } else if (pwr > 30) {
        interval = 5;
    } else if (pwr > 0) {
        interval = 6;
    } else {
        interval = 8;
    }

    if (ledCounter > interval) {
        ledCounter = 0;

        int brightness = (ledBuildin == 0) ? 240 : 255;
        analogWrite(LED_BUILTIN, brightness);
        
        ledBuildin = !ledBuildin;
    }

    ledCounter++;
}

/* Display setup
 */
void displaySetup(Adafruit_SSD1306 &display) {
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(SCREEN_CONTRAST);

    display.clearDisplay(); // Display delete all
    display.setFont(&FreeMonoBold9pt7b);
    display.setTextColor(SSD1306_WHITE);

    display.setCursor(0, 12);
    display.print("Temp1:");
    display.setCursor(0, 25);
    display.print("Temp2:");
    display.setCursor(0, 38);
    display.print("Temp3:");

    display.setCursor(0, 62);
    display.setTextSize(2);
    display.print("PW:");

    display.display(); 
}

/* Send data to server
 */
void sendData() {
    CONNECTED();

    if (client.connect(configWifi.dataServer,
        static_cast<uint16_t>(configWifi.dataServerPort.toInt()) )) {

        client.print("GET /stove?te0=");
        client.print((int)te0);
        client.print("&te1=");
        client.print((int)te1);
        client.print("&te2=");
        client.print((int)te2);
        client.print("&pwr=");
        client.print(pwr);

        client.println(" HTTP/1.1");
        client.print("Host: ");
        client.print(configWifi.dataServer);
        client.println("Connection: close");
        client.println();

        if (client.connected() || client.available()) {
            // Read all data from server
            String line = client.readStringUntil('\n');
            client.stop();
        }
        SLOGLN("Data sent to server");

    } else {
        SLOG("connection failed");
    }    
}

/* Send data to MQTT broker
 */
void mqttSendData() {
    CONNECTED();

    SLOGF("Send data to MQTT: <%s> te0:%d te1:%d te2:%d pwr:%d",
        configWifi.mqttTopic.c_str(), te0, te1, te2, pwr);

    if (!mqttClient.connected()) {
        connectMqtt();
    }
    String message = "{";
    message += "\"te0\":";
    message += te0;
    message += ",\"te1\":";
    message += te1;
    message += ",\"te2:\":";
    message += te2;
    message += ",\"pwr\":";
    message += pwr;
    message += "}";
    mqttClient.publish(configWifi.mqttTopic.c_str(), message.c_str());
}

/* Display rerender
 */
void displayPrint(Adafruit_SSD1306 &display) {

    display.setTextSize(1);

    display.setCursor(65, 12);
    display.fillRect(64, 0, 64, 14, BLACK);
    display.print(te0 > 300 ? ">.." : String(te0));
    display.print("C");

    display.setCursor(65, 25);
    display.fillRect(64, 14, 64, 14, BLACK);
    display.print(te1 > 300 ? ">.." : String(te1));
    display.print("C");
    
    display.setCursor(65, 38);
    display.fillRect(64, 26, 64, 14, BLACK);
    display.print(te2 > 300 ? ">.." : String(te2));
    display.print("C");
    
    display.fillRect(57, 40, 64, 25, BLACK);
    display.setCursor(57, 63);

    display.setTextSize(2);
    display.print(pwr);
    display.print("%");

    display.display(); 

    //SLOGF("Display printed: te0:%d te1:%d te2:%d pwr:%d",
    //    te0, te1, te2, pwr);
}

/* Remap temperature
 */
int remapTemp(int v) {
  return (v < 40 ? 40 : (v > 80 ? 80 : v));
} 

/* Main loop
 */
void loop() {

    server.handleClient();

    if (displayCounter > 50) {
        t0.readTemperature();
        t1.readTemperature();
        t2.readTemperature();
  
        te0 = t0.getCelsius();
        te1 = t1.getCelsius();
        te2 = t2.getCelsius();

        displayPrint(display);

        pwr = map(remapTemp(te0), 40, 80, 0, 100);
        int pwm = map(pwr, 0, 100, 0, 255);
        analogWrite(PWM_PIN, pwm);

        displayCounter = 0;
    }
    displayCounter++;

    if (clientCounter > 3000) {
        sendData();
        clientCounter = 0;
    }
    clientCounter++;

    if (mqttClientCounter > 500) {
        mqttSendData();
        mqttClientCounter = 0;
    }
    mqttClientCounter++;

    delay(10);
}

/* Hard reset function for ESP module
 */
void hardReset() {
    ESP.restart();
}
