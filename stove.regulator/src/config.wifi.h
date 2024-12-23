#ifndef CONFIG_WIFI_H
#define CONFIG_WIFI_H

#include <EEPROM.h>
#include <CRC32.h>
#include "debugutil.h"

#define EEPROM_SIZE 512

class ConfigWifi_t {

public:
    uint32_t checksum;

    String ip;
    String ssid;
    String password;
    String gateway;
    String subnet;
    String dataServer;
    
    String mqtt;
    String mqttUser;
    String mqttPassword;
    String mqttTopic;

    String hostname;

    uint8_t dhcp;

    uint16_t dataPort;
    uint16_t mqttPort;
    uint8_t ssidSize;
    uint8_t passwordSize;
    uint8_t ipSize;
    uint8_t gatewaySize;
    uint8_t subnetSize;

    uint16_t save() {
        //SLOG("\n---------- Save ----------");

        checksum = CRC32::calculate(
            (ssid + password + ip + gateway + subnet).c_str(),
            sizeof(ssid + password + ip + gateway + subnet));

        EEPROM.put(0, checksum);
        SLOGF("Save CRC: %u", checksum);

        EEPROM.put(10, ssidSize);
        SLOGF("Save --> ssidSize: %d", ssidSize);

        EEPROM.put(11, passwordSize);
        SLOGF("Save --> passwordSize: %d", passwordSize);

        EEPROM.put(12, ipSize);
        SLOGF("Save --> ipSize: %d", ipSize);

        EEPROM.put(13, gatewaySize);
        SLOGF("Save --> gatewaySize: %d", gatewaySize);

        EEPROM.put(14, subnetSize);
        SLOGF("Save --> subnetSize: %d", subnetSize);

        EEPROM.put(15, (bool)dhcp);
        SLOGF("Save --> dhcp: %d", dhcp);

        EEPROM.commit();


        uint8_t addr = 20;
        addr = writeString(addr, ssid);
        SLOGF("PUT ssid: <%s> at %d", ssid.c_str(), addr);

        addr = writeString(addr, password);
        SLOGF("PUT password: <%s> at %d", password.c_str(), addr);

        addr = writeString(addr, ip);
        SLOGF("PUT ip: <%s> at %d", ip.c_str(), addr);

        addr = writeString(addr, gateway);
        SLOGF("PUT gw: <%s> at %d", gateway.c_str(), addr);

        addr = writeString(addr, subnet);
        SLOGF("PUT subnet: <%s> at %d", subnet.c_str(), addr);

        EEPROM.commit();

        return addr;
    }

    uint16_t load() {
        SLOGLN("\n---------- LOAD ----------");

        EEPROM.get(0, checksum);
        SLOGF("Load CRC from EEPROM: %u", checksum);

        EEPROM.get(10, ssidSize);
        SLOGF("LOAD ssid size: %d", ssidSize);

        EEPROM.get(11, passwordSize);
        SLOGF("LOAD password size %d", passwordSize);

        EEPROM.get(12, ipSize);
        SLOGF("LOAD ip size  %d", ipSize);

        EEPROM.get(13, gatewaySize);
        SLOGF("LOAD gatewaySize size  %d", gatewaySize);

        EEPROM.get(14, subnetSize);
        SLOGF("LOAD subnetSize size  %d", subnetSize); 

        EEPROM.get(15, dhcp);
        SLOGF("LOAD dhcp %d", dhcp);

        uint8_t addr = 20;
        ssid = readString(addr);
        SLOGF("GET ssid: <%s> from %d", ssid.c_str(), addr);
        addr += ssidSize + 1;

        password = readString(addr);
        SLOGF("GET password <%s> from %d", password.c_str(), addr);

        addr += passwordSize + 1;

        ip = readString(addr);
        SLOGF("GET ip <%s> from %d", ip.c_str(), addr);
        addr += ipSize + 1;

        gateway = readString(addr);
        SLOGF("GET gateway <%s> from %d", gateway.c_str(), addr);
        addr += gatewaySize + 1;

        subnet = readString(addr);
        SLOGF("GET subnet <%s> from %d", subnet.c_str(), addr);
        addr += subnetSize + 1;

        checksum = CRC32::calculate(
            (ssid + password + ip + gateway + subnet).c_str(),
            sizeof(ssid + password + ip + gateway + subnet));

        uint32_t checksumLo;
        EEPROM.get(0, checksumLo);

        SLOGF("Load CRC: %u Calc: %u", checksumLo, checksum);

        // set default values
        if (checksumLo != checksum) {
            ssid = "*****";
            password = "*******";
            ip = gateway = subnet = "";
            SLOGF("ssid: %s", ssid.c_str());
            SLOGF("pass: %s", password.c_str());
        }
        return addr;
    }

    int writeString(char add, String data) {
        int _size = data.length();
        for(int i = 0; i < _size; i++) {
            EEPROM.write(add + i, data[i]);
        }
        EEPROM.write(add + _size, '\0');
        return add + _size + 1;
    }

    String readString(char add) {
        char data[100];
        int len = 0;
        unsigned char k = EEPROM.read(add);
        while(k != '\0' && len < 100) {
            k = EEPROM.read(add + len);
            data[len] = k;
            len++;
        }
        data[len] = '\0';
        return String(data);
    }
};

#endif
