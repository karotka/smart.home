#ifndef CONFIG_H
#define CONFIG_H

#define MACADDRESS 0x66,0x15,0x00,0x00,0x00,0x07
#define MYHOSTNAME "Stove"

#define DATASERVER "192.168.0.222"
#define DATASERVER_PORT 80

#define MQTT_TOPIC "home/stove"

// MQTT broker
const char* mqttServer = "192.168.0.224";   // Name or IP adress MQTT broker
const int mqttPort = 1883;                  // Port 
const char* mqttUser = "";                  // 
const char* mqttPassword = "";              // 

#define PWM_PIN D3

#define SCREEN_WIDTH 128     // Display width
#define SCREEN_HEIGHT 64     // Display height
#define SCREEN_ADDRESS 0x3C  // Display address
#define SCREEN_CONTRAST 0x8F // Initialize contrast value

#endif
