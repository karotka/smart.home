#include <Arduino.h>
#include "Thermistor.h"

Thermistor::Thermistor(uint8_t channel)
    : channel(channel), steinhart(0),
      celsius(0), pointer(0)  {
}

void Thermistor::begin() {
    //analogReference(EXTERNAL);
}

void Thermistor::setMuxChannel(int channel) {
    digitalWrite(MUXPIN_A, channel & 0x01);
    digitalWrite(MUXPIN_B, (channel >> 1) & 0x01);
    digitalWrite(MUXPIN_C, (channel >> 2) & 0x01);
}

float Thermistor::getCelsius() {

    if (pointer != NUMSAMPLES) {
        return 0;
    }
    // average all the samples out
    average = 0;
    for (uint8_t i = 0; i < NUMSAMPLES; i++) {
        average += samples[i];
    }
    average /= NUMSAMPLES;
    
    // convert the value to resistance
    double resistance = (1023.0 / average - 1) * SERIESRESISTOR;
    
    double steinhart;
    steinhart = resistance / NOMINALRESISTANCE;         // (R/Ro)
    steinhart = log(steinhart);                         // ln(R/Ro)
    steinhart /= BCOEFFICIENT;                          // 1/B * ln(R/Ro)
    steinhart += 1.0 / TEMPERATURENOMINAL;   // + (1/To)
    steinhart = 1.0 / steinhart;                        // Invert
    steinhart -= 273.15;                                // convert to C

    return steinhart;
}

void Thermistor::readTemperature() {
    setMuxChannel(channel);
    
    // shift array
    for (uint8_t i = 1; i < NUMSAMPLES; i++) {
        samples[i - 1] = samples[i];
    }
    adc = analogRead(A0);
    samples[NUMSAMPLES - 1] = adc;
    pointer++;

    if (pointer > NUMSAMPLES) {
        pointer = NUMSAMPLES;
    }
}
