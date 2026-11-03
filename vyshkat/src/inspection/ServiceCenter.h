#pragma once

#include "interfaces/InspectionService.h"

// Техосмотр: принимает только новые и исправные устройства.
class ServiceCenter : public InspectionService {
public:
    Inspection inspect(const Inventoriable& item) override;

private:
    bool isAllowed(const Inventoriable& item) const;
    std::string rejectionReason(const Inventoriable& item) const;
};