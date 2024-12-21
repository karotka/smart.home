#ifndef CONFIG_H
#define CONFIG_H

//#define DEBUG 1

#define MACADDRESS 0x66,0x15,0x00,0x00,0x00,0x07
#define MYIPADDR 192,168,1,30
#define MYIPMASK 255,255,254,0
#define MYGW 192,168,1,1
#define MYHOSTNAME "Stove"

#define PINGSERVER "192.168.0.222"

#define LISTENPORT 80

const char *ssid = "KWIFI_2G";       // Your WiFi SSID
const char *password = "Heslicko12"; // Your WiFi Password
const char *pingserver = "192.168.0.222";
const int port = 80;

// MQTT broker
const char* mqttServer = "192.168.0.224";   // Name or IP adress MQTT broker
const int mqttPort = 1883;                  // Port 
const char* mqttUser = "";                  // 
const char* mqttPassword = "";              // 

#define PWM_PIN D3

#define SCREEN_WIDTH 128 // Šířka displeje
#define SCREEN_HEIGHT 64  // Výška displeje
#define SCREEN_ADDRESS 0x3C

//unsigned char
#endif
