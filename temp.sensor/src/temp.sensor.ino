#include <Wire.h>
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

// Any "wait for X" loop reboots after this many ms instead of locking
// up the board until a manual power cycle. Long enough to ride out a
// router reboot, short enough that a wedged sensor is back in service
// within one deep-sleep cycle.
const unsigned long WAIT_TIMEOUT_MS = 30000;

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
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WAIT_TIMEOUT_MS) {
            SLOGLN("WiFi timeout, rebooting");
            ESP.restart();
        }
        SLOG(".");
        delay(500);
        digitalWrite(LED_BUILTIN, st ? HIGH : LOW);
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
        // Soft restart gives the I2C bus a fresh start; one bad boot no
        // longer kills the node forever. The old while(1) wedged here
        // because delay() feeds the watchdog.
        delay(1000);
        ESP.restart();
    }
    SLOGLN("BME connected");

    wifiConnect();
}

void loop() {
    float temperature = 0, humidity = 0, pressure = 0;
    sensors_event_t temp_event, pressure_event, humidity_event;

    // Real averaging: sample inside the loop. The old code called
    // getEvent once outside the loop and added the same value ten
    // times — divided by ten that just gave the original reading back.
    const int N = 10;
    for (int i = 0; i < N; i++) {
        bme_temp->getEvent(&temp_event);
        bme_pressure->getEvent(&pressure_event);
        bme_humidity->getEvent(&humidity_event);
        temperature += temp_event.temperature;
        humidity += humidity_event.relative_humidity;
        pressure += pressure_event.pressure;
        delay(50);
    }
    temperature /= N;
    humidity /= N;
    pressure /= N;

    WiFiClient client;
    client.setTimeout(5000);

    if (client.connect(SERVER_HOST, SERVER_PORT)) {
        SLOGLN("Sending request");
        // printf instead of String chains so the heap doesn't fragment
        // across thousands of wake cycles.
        client.printf(
            "GET /sensorTemp?id=%u&t=%.2f&h=%.2f&p=%.2f HTTP/1.1\r\n"
            "Host: %s\r\n"
            "Connection: close\r\n"
            "\r\n",
            ESP.getChipId(), temperature, humidity, pressure, SERVER_HOST);

        unsigned long start = millis();
        while ((client.connected() || client.available()) &&
               millis() - start < WAIT_TIMEOUT_MS) {
            if (client.available()) {
                String line = client.readStringUntil('\n');
                SLOG(line);
            } else {
                yield();   // let the WiFi stack tick so WDT doesn't trip
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
