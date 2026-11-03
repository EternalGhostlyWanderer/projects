#ifndef FILTER_DESCRIPTOR_H
#define FILTER_DESCRIPTOR_H
#include <string>
#include <vector>

struct FilterDescriptor {
    std::string name;
    std::vector<std::string> params;
};

#endif //FILTER_DESCRIPTOR_H
