#include <Wire.h>
#include <SPI.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <ESP8266WiFi.h>
#include "config.h"

Adafruit_BMP280 bme; // I2C

const char* host = "192.168.0.61";
Config_t config;

void wifiConnect() {

    //WiFi.config(config.ip, config.gateway, config.subnet);
    //WiFi.mode(WIFI_STA);
    WiFi.begin(config.ssid.c_str(), config.password.c_str());

    bool st = true;
    while (WiFi.status() != WL_CONNECTED) {
        delay(250);
        //Serial.print(".");
        if (st) digitalWrite(LED_BUILTIN, HIGH);
        else digitalWrite(LED_BUILTIN, LOW);
        st = !st;
    }
    Serial.println("");
    Serial.print("WiFi connected: ");
    Serial.print("http://");
    Serial.print(WiFi.localIP().toString());
    Serial.println("/");
    digitalWrite(LED_BUILTIN, LOW);
    analogWrite(LED_BUILTIN, 1000);
}


void setup() {

    Serial.begin(115200);
    Serial.println(F("BMP280 test"));

    if (!bme.begin()) {
        Serial.println("Could not find a valid BMP280 sensor, check wiring!");
        while (1);
    }

    wifiConnect();
}

void loop() {

    WiFiClient client;
    if (client.connect(host, 8080)) {
        Serial.println("connected]");

        Serial.println("[Sending a request]");
        client.print(String("GET /?t=") + bme.readTemperature() + " HTTP/1.1\r\n" +
                 "Host: " + host + "\r\n" +
                 "Connection: close\r\n" +
                 "\r\n"
                );

        Serial.println("[Response:]");
        while (client.connected() || client.available()) {
            if (client.available()) {
                String line = client.readStringUntil('\n');
                Serial.println(line);
            }
        }
        client.stop();
        Serial.println("\n[Disconnected]");

    } else {

        Serial.println("connection failed!]");
        client.stop();
    }

    Serial.print("Temperature = ");
    Serial.print(bme.readTemperature());
    Serial.println(" *C");

    Serial.print("Pressure = ");
    Serial.print(bme.readPressure());
    Serial.println(" Pa");

    Serial.print("Approx altitude = ");
    Serial.print(bme.readAltitude(1013.25)); // this should be adjusted to your local forcase
    Serial.println(" m");

    Serial.println();
    ESP.deepSleep(60e6);
    //delay(2000);
}