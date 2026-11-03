#pragma once

#include <string>

#include "models/transport/Transport.h"

class Scooter : public Transport {
public:
    Scooter(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition,
        int simplicity
    );

    std::string getKind() const override;
};