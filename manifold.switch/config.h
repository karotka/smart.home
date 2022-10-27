#ifndef CONFIG_H
#define CONFIG_H

//#define DEBUG 1
#define SCREEN_ADDRESS 0x3C ///< See datasheet for Address; 0x3D for 128x64, 0x3C for 128x32

#define MACADDRESS 0x66,0x15,0x00,0x00,0x00,0x05
#define MYIPADDR 192,168,0,5
#define MYIPMASK 255,255,254,0
#define MYGW 192,168,1,1
#define PINGSERVER 192,168,0,222

#define LISTENPORT 80

//unsigned char
#endif
