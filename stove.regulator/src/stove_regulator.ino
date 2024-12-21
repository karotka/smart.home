#include <ESP8266WiFi.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Fonts/FreeMonoBold9pt7b.h>
#include <PubSubClient.h>

#include "thermistor.h"
#include "config.h"
#include <Ticker.h>

WiFiServer server(LISTENPORT);
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
WiFiClient client; // Use WiFiClient class to create TCP connections
PubSubClient mqttClient(client);

Thermistor t0(0, 0);
Thermistor t1(1, 0);
Thermistor t2(2, 0);

volatile int te0 = 0;
volatile int te1 = 0;
volatile int te2 = 0;
volatile int pwr = 0;
volatile int clientCounter = 0;
volatile int mqttClientCounter = 0;


void (*resetFunct)(void) = 0;

void setContrast(Adafruit_SSD1306 &display, uint8_t contrast) {
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(contrast);
}

void setup()
{
    Serial.begin(9600);

    IPAddress ip(MYIPADDR);
    IPAddress gateway(MYGW);
    IPAddress subnet(MYIPMASK);

    WiFi.config(ip, gateway, subnet);
    WiFi.mode(WIFI_STA);
    WiFi.hostname(MYHOSTNAME);
    WiFi.begin(ssid, password);
    
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }

    Serial.print("Connected to WiFi. IP address: ");
    Serial.println(WiFi.localIP());

    server.begin();

    // pins for mux
    pinMode(muxPinA, OUTPUT);
    pinMode(muxPinB, OUTPUT);
    pinMode(muxPinC, OUTPUT);

    // Připojení k MQTT brokeru
    mqttClient.setServer(mqttServer, mqttPort);
    
    // Přihlášení, pokud je potřeba
    if (mqttClient.connect("ESP8266Client"/*, mqttUser, mqttPassword */)) {
        Serial.println("Připojeno k MQTT brokeru");
    } else {
        Serial.print("Nepodařilo se připojit k MQTT, chyba: ");
        Serial.print(mqttClient.state());
    }

    // Display Init
    if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
        Serial.println(F("Cannot inicialized OLED!"));
        while (true); // Stop
    }

    setContrast(display, 0);
    display.clearDisplay(); // Disply delete
    display.setFont(&FreeMonoBold9pt7b);

    //display.setTextSize(2);     
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

    Serial.println(ESP.getResetReason());
}

void sendData() {
    
    if (client.connect(pingserver, port)) {

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
        client.print(pingserver);
        client.println("Connection: close");
        client.println();

        // Read all from server
        
        if (client.connected() || client.available()) {
            String line = client.readStringUntil('\n');
            client.stop();
        }
        
        //Serial.println("Send Done.");

    } else {
        Serial.println("connection failed");
    }    

}

void mqttSendData() {

    if (!mqttClient.connected()) {
        mqttReconnect();
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
    mqttClient.publish("home/stove", message.c_str());

}

// Funkce pro opětovné připojení
void mqttReconnect() {
    while (!mqttClient.connected()) {
        Serial.print("Pokouším se připojit k MQTT brokeru...");
        // Zkusíme se znovu připojit
        if (mqttClient.connect("ESP8266Client"/*, mqttUser, mqttPassword*/)) {
            Serial.println("Připojeno k MQTT brokeru");
        } else {
            Serial.print("Nepodařilo se připojit, chyba: ");
            Serial.print(mqttClient.state());
            delay(2000); // Odložení před dalším pokusem
        }
    }
}

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

    //Serial.println(te0);
}

int remapTemp(int v) {
  return (v < 40 ? 40 : (v > 80 ? 80 : v));
} 

void loop() {

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

    if (clientCounter > 30) {
        sendData();
        clientCounter = 0;
    }
    clientCounter++;

    if (mqttClientCounter > 5) {
        mqttSendData();
        mqttClientCounter = 0;
    }
    mqttClientCounter++;

    delay(1000);
    
}