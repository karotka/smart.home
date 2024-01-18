#ifndef CONFIG_H
#define CONFIG_H

//#include "EEPROM.h"

//#define DEBUG 1

#define MQTT_BROKER "192.168.0.224"
#define MQTT_PORT 1883
#define MQTT_TOPIC "temperature/loznice"
#define DEEP_SLEEP  20e6


class Config_t {

public:
    String ssid = "KWIFI_2G";
    String password = "**********";
    IPAddress ip;
    IPAddress dns;
    IPAddress gateway;
    IPAddress subnet;
    String hostname;
    uint8_t apMode;
    bool dhcp = false;
    bool ap = false;

    Config_t() :
        ip(192, 168, 1, 14),
        dns(192, 168, 1, 1),
        gateway(192, 168, 1, 1),
        subnet(255, 255, 254, 0) {};

};


#endif
