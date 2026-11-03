#pragma once

#include <string>

#include "enums/InspectionResult.h"

class Inspection {
public:
    explicit Inspection(InspectionResult result, std::string reason = "");

    bool isPassed() const;
    const std::string& getReason() const;

private:
    InspectionResult result_;
    std::string reason_;
};
