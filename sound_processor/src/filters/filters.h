#ifndef FILTERS_H
#define FILTERS_H
#include "../waveform/waveform.h"

#include <map>
#include <stdexcept>
#include <string>
#include <string_view>

class Filter
{
public:
    virtual ~Filter() = default;
    virtual void apply(Waveform* sound) = 0;

    virtual Filter* clone() const = 0;
};

class AmplFilter: public Filter
{
public:
    AmplFilter(double factor);
    void apply(Waveform* sound) override;

    Filter* clone() const override { return new AmplFilter(*this); }

private:
    double _factor;
};

class NormFilter: public Filter
{
public:
    explicit NormFilter(double peak = 1);
    void apply(Waveform* sound) override;

    Filter* clone() const override { return new NormFilter(*this); }

private:
    double _peak;
};

class SilenceFilter: public Filter
{
public:
    SilenceFilter(std::string_view unit, double start, double end);

    void apply(Waveform* sound) override;

    Filter* clone() const override { return new SilenceFilter(*this); }

private:
    std::string_view _unit;
    double _start;
    double _end;
};

class TimestretchFilter: public Filter
{
public:
    TimestretchFilter(double factor);
    void apply(Waveform* sound) override;

    Filter* clone() const override { return new TimestretchFilter(*this); }

private:
    double _factor;
};

class LowpassFilter: public Filter
{
public:
    LowpassFilter(int windowSize);
    void apply(Waveform* sound) override;

    Filter* clone() const override { return new LowpassFilter(*this); }

private:
    int _windowSize;
};

namespace FilterDocs {  // сообщения об ошибках
inline std::string AMPL_HELP =
    "Usage: -f ampl <factor>\nParameters:\n    <factor> - floating point "
    "number >= 0\n";

inline std::string NORMALIZE_HELP =
    "Usage: -f normalize [peak]\nParameters:\n    [peak] - floating point "
    "number in [0, 1]\n";

inline std::string SILENCE_HELP =
    "Usage: -f silence (sec|ms) <start> <end>\nParameters:\n    (sec|ms) - "
    "time unit selection ( sec' or 'ms')\n    <start> - floating point number "
    ">= 0\n    <end> - floating point number > <start>\n";

inline std::string TIMESTRETCH_HELP =
    "Usage: -f timestretch <factor>\nParameters:\n    <factor> - floating "
    "point number > 0\n";

inline std::string LOWPASS_HELP =
    "Usage: -f lowpass <window_size>\nParameters:\n    <window_size> - "
    "integer odd number >= 1\n";

inline std::string GENERATOR_SIN_HELP =
    "Usage: -f generator sin <frequency_hz> <duration_ms>\nParameters:\n    "
    "<frequency_hz> - floating point number >= 0\n    <duration_ms> - floating "
    "point number >= 0\n";

inline std::string GENERATOR_AM_HELP =
    "Usage: -f generator am <amplitude> <carrier_hz> <modulation_hz> <depth> "
    "<duration_ms>\nParameters:\n    <amplitude> - floating point number in "
    "[0, 1]\n    <carrier_hz> - floating point number >= 0\n    "
    "<modulation_hz> - floating point number >= 0\n    <depth> - floating "
    "point number in [0, 1]\n    <duration_ms> - floating point number >= 0\n";

inline std::string GENERATOR_FM_HELP =
    "Usage: -f generator fm <amplitude> <carrier_hz> <modulation_hz> "
    "<deviation_hz> <duration_ms>\nParameters:\n    <amplitude> - floating "
    "point number in [0, 1]\n    <carrier_hz> - floating point number >= 0\n   "
    " <modulation_hz> - floating point number > 0\n    <deviation_hz> - "
    "floating point number >= 0\n    <duration_ms> - floating point number >= "
    "0\n";

inline const std::map<std::string_view, std::string_view> HELP_MAP = {
    {"ampl", AMPL_HELP},       {"normalize", NORMALIZE_HELP},
    {"silence", SILENCE_HELP}, {"timestretch", TIMESTRETCH_HELP},
    {"lowpass", LOWPASS_HELP}, {"sin", GENERATOR_SIN_HELP},
    {"am", GENERATOR_AM_HELP}, {"fm", GENERATOR_FM_HELP}};

inline std::string_view getHelp(std::string_view filterName)
{
    auto it = HELP_MAP.find(filterName);
    if(it != HELP_MAP.end())
        return it->second;
    return "unknown filter!";
}
}  // namespace FilterDocs

#endif  // FILTERS_H
