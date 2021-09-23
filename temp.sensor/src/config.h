#ifndef CONFIG_H
#define CONFIG_H

#include "EEPROM.h"

#define EEPROM_SIZE 512


class Config_t {

public:
    String ssid = "KWIFI";
    String password = "Heslicko12";
    IPAddress ip;
    IPAddress gateway;
    IPAddress subnet;
    uint8_t apMode;

    Config_t() :
        ip(192, 168, 0, 12),
        gateway(192, 168, 0, 1),
        subnet(255, 255, 255, 0) {};

};


#endif
