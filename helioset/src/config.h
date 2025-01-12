#ifndef CONFIG_H
#define CONFIG_H

#define MACADDRESS 0x66,0x15,0x00,0x00,0x00,0x09
#define MYHOSTNAME "helioset"

#define PWM_PIN 3

#define T_CS 5


#define SCREEN_WIDTH 320     // Display width
#define SCREEN_HEIGHT 240    // Display height

#define COLOR_MENU ILI9341_WHITE

#define CONNECTED() \
    if (setting.apMode) { \
        SLOG("AP mode"); \
        return; \
    }

#endif

#define NTP_SERVER  "pool.ntp.org" // Volitelné: můžete použít jiný NTP server
#define GMT_OFFSET_SEC 3600 // GMT offset (např. +1 hodina = 3600 sekund)
#define DAYLIGHT_OFFSET_SEC 3600 // Časový posun pro letní čas (pokud je potřeba)
#define UPDATE_INTERVAL 60000 // Interval pro aktualizaci času (v milisekundách)

#define LINE_SPACING 28


