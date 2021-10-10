#include <Wire.h>
#include <SPI.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <ESP8266WiFi.h>
#include "config.h"
#include <debugutil.h>

Config_t config;

Adafruit_BME280 bme; // use I2C interface
Adafruit_Sensor *bme_temp = bme.getTemperatureSensor();
Adafruit_Sensor *bme_pressure = bme.getPressureSensor();
Adafruit_Sensor *bme_humidity = bme.getHumiditySensor();

void wifiConnect() {

    if (config.ap) {
        WiFi.disconnect();
        WiFi.softAPConfig(
            IPAddress(192,168,5,10),
            IPAddress(192,168,5,1),
            IPAddress(255,255,255,0));
        WiFi.softAP(config.hostname);
        return;
    } else {
        WiFi.mode(WIFI_STA);
    }

    if (!config.dhcp) {
        WiFi.config(config.ip, config.dns, config.gateway, config.subnet);
        SLOGLN("WiFi in static mode");
    } else {
        SLOGLN("WiFi in DHCP mode");
    }

    WiFi.begin(config.ssid.c_str(), config.password.c_str());

    bool st = true;
    while (WiFi.waitForConnectResult() != WL_CONNECTED) {
        //Serial.printf("Connection status: %d\n", WiFi.status());
        //WiFi.printDiag(Serial);
        //delay(1000);
        //Serial.print(".");

        SLOG(".");
        delay(500);
        if (st) digitalWrite(LED_BUILTIN, HIGH);
        else digitalWrite(LED_BUILTIN, LOW);
        st = !st;
    }
    SLOGLN("");
    SLOGLN("WiFi connected: ");
    SLOGF("http://%s/", WiFi.localIP().toString().c_str());
    digitalWrite(LED_BUILTIN, LOW);
    analogWrite(LED_BUILTIN, 1000);
}

void setup() {
#ifdef DEBUG
    Serial.begin(115200);
#endif
    if (!bme.begin()) {
        SLOGLN("Could not find a valid BME280 sensor!");
        while (1) delay(10);
    }
    SLOGLN("BME connected");

    wifiConnect();
}

void loop() {
    float temperature, humidity, pressure;
    sensors_event_t temp_event, pressure_event, humidity_event;
    bme_temp->getEvent(&temp_event);
    bme_pressure->getEvent(&pressure_event);
    bme_humidity->getEvent(&humidity_event);

    for (int i = 0; i < 10; i++) {
        temperature += temp_event.temperature;
        humidity += humidity_event.relative_humidity;
        pressure += pressure_event.pressure;
        delay(50);
    }
    temperature = temperature / 10;
    pressure = pressure / 10;
    humidity = humidity / 10;

    String clientId(ESP.getChipId());
    WiFiClient client;

    if (client.connect(SERVER_HOST, SERVER_PORT)) {
        SLOGLN("Sending request");
        client.print(
            String("GET /?id=") + clientId +
            String("&t=") + temperature +
            String("&h=") + humidity +
            String("&p=") + pressure +
            " HTTP/1.1\r\n" +
            "Host: " + SERVER_HOST + "\r\n" +
            "Connection: close\r\n" +
            "\r\n");

        while (client.connected() || client.available()) {
            if (client.available()) {
                String line = client.readStringUntil('\n');
                SLOG(line);
            }
        }
        client.stop();

    } else {
        SLOG("connection failed!");
        client.stop();
    }

    SLOGF("Temperature = %.2f*C", temperature);
    SLOGF("Humidity = %.2f pct", humidity);
    SLOGF("Pressure = %.2fhPa", pressure);
    SLOGLN("Sleep ....");
    ESP.deepSleep(DEEP_SLEEP);
}