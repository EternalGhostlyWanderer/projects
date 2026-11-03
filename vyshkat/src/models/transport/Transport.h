#pragma once

#include <string>

#include "models/Asset.h"

class Transport : public Asset {
public:
    Transport(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition,
        int simplicity
    );

    int getSimplicity() const;

protected:
    int simplicity_;
};