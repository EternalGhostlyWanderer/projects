#pragma once

#include <string>

#include "models/transport/Transport.h"

class Bicycle : public Transport {
public:
    Bicycle(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition,
        int simplicity
    );

    std::string getKind() const override;
};