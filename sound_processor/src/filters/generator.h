#ifndef GENERATOR_H
#define GENERATOR_H
#include "filters.h"

class SinGenFilter: public Filter
{
public:
    SinGenFilter(double frequency, double duration);
    void apply(Waveform* sound) override;

    Filter* clone() const override { return new SinGenFilter(*this); }

protected:
    double _frequency, _duration;
};

class AmGenFilter: public Filter
{
public:
    AmGenFilter(double amplitude, double carrier, double modulation,
                double depth, double duration);
    void apply(Waveform* sound) override;
    Filter* clone() const override { return new AmGenFilter(*this); }

protected:
    double _amplitude, _carrier, _modulation, _depth, _duration;
};

class FmGenFilter: public Filter
{
public:
    FmGenFilter(double amplitude, double carrier, double modulation,
                double deviation, double duration);
    void apply(Waveform* sound) override;

    Filter* clone() const override { return new FmGenFilter(*this); }

protected:
    double _amplitude, _carrier, _modulation, _deviation, _duration;
};

#endif  // GENERATOR_H
