#include "models/items/InventoryItem.h"

#include <utility>

InventoryItem::InventoryItem(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition
)
    : Asset(
          std::move(inventoryNumber),
          std::move(name),
          condition
      ) {}