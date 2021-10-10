#ifndef CONFIG_H
#define CONFIG_H

#include "EEPROM.h"

//#define DEBUG 1

#define SERVER_HOST "192.168.1.250"
#define SERVER_PORT 80
#define EEPROM_SIZE 512
#define DEEP_SLEEP  60e6


class Config_t {

public:
    String ssid = "KWIFI_2G";
    String password = "Heslicko12";
    IPAddress ip;
    IPAddress dns;
    IPAddress gateway;
    IPAddress subnet;
    String hostname;
    uint8_t apMode;
    bool dhcp = false;
    bool ap = false;

    Config_t() :
        ip(192, 168, 1, 13),
        dns(192, 168, 1, 1),
        gateway(192, 168, 1, 1),
        subnet(255, 255, 255, 0) {};

};


#endif
