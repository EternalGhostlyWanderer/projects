#ifndef STD_FILTER_PRODUCERS_H
#define STD_FILTER_PRODUCERS_H
#include "../filters/filters.h"
#include "../filter_descriptor.h"
namespace FilterProducers {
Filter* amplFilterCreator(const FilterDescriptor& fd);
Filter* normFilterCreator(const FilterDescriptor& fd);
Filter* silenceFilterCreator(const FilterDescriptor& fd);
Filter* timestretchFilterCreator(const FilterDescriptor& fd);
Filter* lowpassFilterCreator(const FilterDescriptor& fd);
Filter* generatorSinFilterCreator(const FilterDescriptor& fd);
Filter* generatorAmFilterCreator(const FilterDescriptor& fd);
Filter* generatorFmFilterCreator(const FilterDescriptor& fd);
}  // namespace FilterProducers

#endif  // STD_FILTER_PRODUCERS_H
