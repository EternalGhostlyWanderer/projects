#include "inspection/Inspection.h"

#include <utility>

Inspection::Inspection(InspectionResult result, std::string reason)
    : result_(result), reason_(std::move(reason)) {}

bool Inspection::isPassed() const {
    return result_ == InspectionResult::PASSED;
}

const std::string& Inspection::getReason() const {
    return reason_;
}
