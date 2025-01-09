#ifndef CONFIG_H
#define CONFIG_H

#define MACADDRESS 0x66,0x15,0x00,0x00,0x00,0x07
#define MYHOSTNAME "Stove"

#define PWM_PIN D3

#define SCREEN_WIDTH 128     // Display width
#define SCREEN_HEIGHT 64     // Display height
#define SCREEN_ADDRESS 0x3C  // Display address
#define SCREEN_CONTRAST 0x8F // Initialize contrast value

#define CONNECTED() \
    if (setting.apMode) { \
        SLOG("AP mode"); \
        return; \
    }

#endif
