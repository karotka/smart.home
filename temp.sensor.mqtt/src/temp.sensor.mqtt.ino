#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include "config.h"
#include <debugutil.h>

Config_t config;

// Inicializace objektu BME280
Adafruit_BME280 bme;

// Inicializace objektu WiFi klienta
WiFiClient espClient;

// Inicializace objektu MQTT klienta
PubSubClient client(espClient);

void callback(char* topic, byte* payload, unsigned int length) {
  // Obsluha zpráv příchozích na MQTT
}

void mqttConnect() {
    client.setServer(MQTT_BROKER, MQTT_PORT);
    client.setCallback(callback);
    while (!client.connected()) {
        if (client.connect("ESP8266Client")) {
            Serial.println("Připojeno k MQTT brokeru");
        } else {
            Serial.print("Chyba připojení k MQTT brokeru, chybový kód=");
            Serial.println(client.state());
            delay(2000);
        }
    }
}

void wifiConnect() {

    WiFi.mode(WIFI_STA);

    WiFi.config(config.ip, config.dns, config.gateway, config.subnet);
    SLOGLN("WiFi in static mode");

    WiFi.begin(config.ssid.c_str(), config.password.c_str());

    bool st = true;
    while (WiFi.waitForConnectResult() != WL_CONNECTED) {
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
    delay(500);
    digitalWrite(LED_BUILTIN, HIGH);
}

void bmeConnect() {
    // Inicializace BME280
    if (!bme.begin(0x76)) {
        //Serial.println("Nelze nalézt senzor BME280, zkontrolujte zapojení!");
        while(1);
    }
}

void setup() {
#ifdef DEBUG
    Serial.begin(115200);
#endif

    // Připojení k WiFi
    wifiConnect();

    // Připojení k MQTT brokeru
    mqttConnect();
}

void loop() {
    bmeConnect();

    // Měření teploty, vlhkosti a tlaku
    float temperature = bme.readTemperature();
    float humidity = bme.readHumidity();
    float pressure = bme.readPressure() / 100.0F;
    float altitude = bme.readAltitude(1013.25);

    // Odeslání hodnot na MQTT broker
    String tempString = String(temperature);
    String humString = String(humidity);
    String pressString = String(pressure);
    String altString = String(altitude);

    String clientId(ESP.getChipId());

    String mqttPayload =
        "{\"id\":" + clientId +
        ",\"temperature\":" + tempString +
        ",\"humidity\":" + humString +
        ",\"altitude\":" + altString +
        ",\"pressure\":" + pressString + "}";
    client.publish(MQTT_TOPIC, mqttPayload.c_str(), true);

    delay(20000);
}