// temp. for nominal resistance (almost always 25 C)
#define TEMPERATURENOMINAL 298.15

// the value of the 'other' resistor
#define SERIESRESISTOR 100000

// how many samples to take and average, more takes longer
// but is more 'smooth'
#define NUMSAMPLES 10
#define BCOEFFICIENT 3950
#define NOMINALRESISTANCE 100000

//#define MUXPIN_A D6
//#define MUXPIN_B D7
//#define MUXPIN_C D8


class Thermistor {

public:
    Thermistor(uint8_t channel);

    void begin();
    void setMuxChannel(int channel);
    void readTemperature();
    float getCelsius();
    int getAdc() { return adc; };
    bool isEnabled() { return adc == 1023 ? false : true; };

protected:
    uint8_t channel;
    float samples[NUMSAMPLES];
    float steinhart;
    float celsius;
    float average;
    int16_t adc;
    uint32_t thermistornominal;
    int bcoefficient;
    uint8_t pointer;
};
