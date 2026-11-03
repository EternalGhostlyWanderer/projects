#pragma once

#include <string>

#include "models/Asset.h"

class InventoryItem : public Asset {
public:
    InventoryItem(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition
    );
};