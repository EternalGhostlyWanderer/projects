#ifndef PIPELINE_H
#define PIPELINE_H

#include "../filters/filters.h"
#include "../waveform/waveform.h"

class Pipeline
{
public:
    Pipeline() {};
    Pipeline(const Pipeline& other);
    Pipeline& operator=(const Pipeline& other);
    Pipeline(Pipeline&& other) noexcept;
    Pipeline& operator=(Pipeline&& other) noexcept;
    ~Pipeline();

    void apply(Waveform* sound);

public:
    Filter* addFilter(Filter* filter);
    size_t getFilterNumbers() const;
    Filter* operator[](size_t i);
    const Filter* operator[](size_t i) const;

protected:
    std::vector<Filter*> _filters;
};

#endif  // PIPELINE_H
