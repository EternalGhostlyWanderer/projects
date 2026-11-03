#ifndef PIPELINE_BUILDER_H
#define PIPELINE_BUILDER_H
#include "../filter_descriptor.h"
#include "../pipeline/pipeline.h"
#include <map>
#include <vector>

using FilterProducer = Filter* (*)(const FilterDescriptor&);
class PipelineBuilder
{
public:
    Pipeline createPipeline(std::vector<FilterDescriptor>& FilterDescriptor);

    void addFilterProducer(std::string_view filterName, FilterProducer);
    FilterProducer getFilterProducer(std::string_view filterName);

private:
    std::map<std::string_view, FilterProducer> _producers;
};

#endif  // PIPELINE_BUILDER_H
