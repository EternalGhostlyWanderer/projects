#pragma once

#include <string>

#include "models/items/InventoryItem.h"

class DockingStation : public InventoryItem {
public:
    DockingStation(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition
    );

    std::string getKind() const override;
};