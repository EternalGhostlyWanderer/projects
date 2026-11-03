#include "pipeline.h"
Pipeline::Pipeline(const Pipeline& other)
{
    _filters.reserve(other._filters.size());
    for(Filter* filter: other._filters)
        if(filter)
            _filters.push_back(filter->clone());
}
Pipeline::~Pipeline()
{
    for(Filter* filter: _filters)
        delete filter;
}
Pipeline& Pipeline::operator=(const Pipeline& other)
{
    if(this == &other)
        return *this;
    for(Filter* filter: _filters)
        delete filter;
    _filters.clear();

    _filters.reserve(other._filters.size());
    for(Filter* filter: other._filters)
        if(filter)
            _filters.push_back(filter->clone());
    return *this;
}

Pipeline::Pipeline(Pipeline&& other) noexcept
{
    _filters = std::move(other._filters);
}
Pipeline& Pipeline::operator=(Pipeline&& other) noexcept
{
    if(this == &other)
        return *this;
    for(Filter* filter: _filters)
        delete filter;
    _filters.clear();
    _filters = other._filters;
    other._filters.clear();
    return *this;
}

Filter* Pipeline::addFilter(Filter* filter)
{
    _filters.push_back(filter);
    return filter;
}

size_t Pipeline::getFilterNumbers() const { return _filters.size(); }
Filter* Pipeline::operator[](size_t i)  { return _filters[i]; }
const Filter* Pipeline::operator[](size_t i) const { return _filters[i]; }

void Pipeline::apply(Waveform* sound)
{
    for(Filter* filter: _filters)
        filter->apply(sound);
}
