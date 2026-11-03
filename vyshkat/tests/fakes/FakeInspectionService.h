#pragma once

#include <cstddef>
#include <string>
#include <vector>
#include "enums/InspectionResult.h"
#include "interfaces/InspectionService.h"

// Подмена техосмотра в тестах: возвращает заданный результат (stub) и запоминает, какие объекты ему показывали (spy).
class FakeInspectionService : public InspectionService {
public:
    explicit FakeInspectionService(
        InspectionResult result = InspectionResult::PASSED
    )
        : result_(result) {}

    Inspection inspect(const Inventoriable& item) override {
        inspectedNumbers_.push_back(item.getInventoryNumber());
        return Inspection(result_);
    }

    void setResult(InspectionResult result) { result_ = result; }

    std::size_t callCount() const { return inspectedNumbers_.size(); }

    const std::vector<std::string>& inspectedNumbers() const {
        return inspectedNumbers_;
    }

private:
    InspectionResult result_;
    std::vector<std::string> inspectedNumbers_;
};
