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
    String dataServerPort;
    String mqttServer;
    String mqttPort;
    String mqttPassword;
    String mqttUser;
    String mqttTopic;
    String hostname;
    int8_t dhcp;

    int8_t ipSize;
    int8_t ssidSize;
    int8_t passwordSize;
    int8_t gatewaySize;
    int8_t subnetSize;
    int8_t dataServerSize;
    int8_t dataPortSize;
    int8_t mqttServerSize;
    int8_t mqttPortSize;
    int8_t mqttUserSize;
    int8_t mqttPasswordSize;
    int8_t mqttTopicSize;

    ConfigWifi_t() {
        ssid = "*****";
        password = "*******";
        ip = gateway = subnet = dataServer = dataServerPort = mqttServer = mqttPort = mqttUser = mqttPassword = mqttTopic = "";
        dhcp = 1;
        checksum = 0;
        ssidSize = passwordSize = ipSize = gatewaySize = subnetSize = 0;
        dataServerSize = dataPortSize = mqttServerSize = mqttPortSize = mqttUserSize = mqttPasswordSize = mqttTopicSize = 0;
    }

    uint16_t save() {
        SLOGLN("\n---------- Save ----------");

        checksum = CRC32::calculate(
            (ssid + password + ip + gateway + subnet + dataServer + dataServerPort + mqttServer +
             mqttPort + mqttUser + mqttPassword + mqttTopic).c_str(),
            sizeof(ssid + password + ip + gateway + subnet + dataServer + dataServerPort + mqttServer +
             mqttPort + mqttUser + mqttPassword + mqttTopic));

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

        EEPROM.put(16, dataServerSize);
        SLOGF("Save --> dataServerSize: %d", dataServerSize);

        EEPROM.put(17, dataPortSize);
        SLOGF("Save --> dataPortSize: %d", dataPortSize);
        
        EEPROM.put(18, mqttServerSize);
        SLOGF("Save --> mqttSize: %d", mqttServerSize);

        EEPROM.put(19, mqttPortSize);
        SLOGF("Save --> mqttPortSize: %d", mqttPortSize);
        
        EEPROM.put(20, mqttUserSize);
        SLOGF("Save --> mqttUserSize: %d", mqttUserSize);

        EEPROM.put(21, mqttPasswordSize);
        SLOGF("Save --> mqttPasswordSize: %d", mqttPasswordSize);

        EEPROM.put(22, mqttTopicSize);
        SLOGF("Save --> mqttTopicSize: %d", mqttTopicSize);

        //EEPROM.commit();

        int8_t addr = 25;
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

        addr = writeString(addr, dataServer);
        SLOGF("PUT dataServer: <%s> at %d", dataServer.c_str(), addr);

        addr = writeString(addr, dataServerPort);
        SLOGF("PUT dataServerPort: <%s> at %d", dataServerPort.c_str(), addr);

        addr = writeString(addr, mqttServer);
        SLOGF("PUT mqttServer: <%s> at %d", mqttServer.c_str(), addr);

        addr = writeString(addr, mqttPort);
        SLOGF("PUT mqttPort: <%s> at %d", mqttPort.c_str(), addr);

        addr = writeString(addr, mqttUser);
        SLOGF("PUT mqttUser: <%s> at %d", mqttUser.c_str(), addr);

        addr = writeString(addr, mqttPassword);
        SLOGF("PUT mqttPassword: <%s> at %d", mqttPassword.c_str(), addr);

        addr = writeString(addr, mqttTopic);
        SLOGF("PUT mqttTopic: <%s> at %d", mqttTopic.c_str(), addr);


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

        EEPROM.get(16, dataServerSize);
        SLOGF("LOAD dataServerSize %d", dataServerSize);

        EEPROM.get(17, dataPortSize);
        SLOGF("LOAD dataPortSize %d", dataPortSize);

        EEPROM.get(18, mqttServerSize);
        SLOGF("LOAD mqttSize %d", mqttServerSize);

        EEPROM.get(19, mqttPortSize);
        SLOGF("LOAD mqttPortSize %d", mqttPortSize);

        EEPROM.get(20, mqttUserSize);
        SLOGF("LOAD mqttUserSize %d", mqttUserSize);

        EEPROM.get(21, mqttPasswordSize);
        SLOGF("LOAD mqttPasswordSize %d", mqttPasswordSize);

        EEPROM.get(22, mqttTopicSize);
        SLOGF("LOAD mqttTopicSize %d", mqttTopicSize);



        int8_t addr = 25;
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

        dataServer = readString(addr);
        SLOGF("GET dataServer <%s> from %d", dataServer.c_str(), addr);
        addr += dataServerSize + 1;

        dataServerPort = readString(addr);
        SLOGF("GET dataServerPort <%s> from %d", dataServerPort.c_str(), addr);
        addr += dataPortSize + 1;

        mqttServer = readString(addr);
        SLOGF("GET mqttServer <%s> from %d", mqttServer.c_str(), addr);
        addr += mqttServerSize + 1;

        mqttPort = readString(addr);
        SLOGF("GET mqttPort <%s> from %d", mqttPort.c_str(), addr);
        addr += mqttPortSize + 1;

        mqttUser = readString(addr);
        SLOGF("GET mqttUser <%s> from %d", mqttUser.c_str(), addr);
        addr += mqttUserSize + 1;

        mqttPassword = readString(addr);
        SLOGF("GET mqttPassword <%s> from %d", mqttPassword.c_str(), addr);
        addr += mqttPasswordSize + 1;

        mqttTopic = readString(addr);
        SLOGF("GET mqttTopic <%s> from %d", mqttTopic.c_str(), addr);
        addr += mqttTopicSize + 1;

        checksum = CRC32::calculate(
            (ssid + password + ip + gateway + subnet + dataServer + dataServerPort + mqttServer +
             mqttPort + mqttUser + mqttPassword + mqttTopic).c_str(),
            sizeof(ssid + password + ip + gateway + subnet + dataServer + dataServerPort + mqttServer +
             mqttPort + mqttUser + mqttPassword + mqttTopic));

        uint32_t checksumLo;
        EEPROM.get(0, checksumLo);

        SLOGF("Load CRC: %u Calc: %u", checksumLo, checksum);

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