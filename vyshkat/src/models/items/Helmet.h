#pragma once

#include <string>

#include "models/items/InventoryItem.h"

class Helmet : public InventoryItem {
public:
    Helmet(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition,
        std::string size
    );

    std::string getSize() const;
    std::string getKind() const override;

private:
    std::string size_;
};