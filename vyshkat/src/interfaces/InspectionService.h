#pragma once

#include "inspection/Inspection.h"
#include "interfaces/Inventoriable.h"

class InspectionService {
public:
    virtual ~InspectionService() = default;

    virtual Inspection inspect(const Inventoriable& item) = 0;
};