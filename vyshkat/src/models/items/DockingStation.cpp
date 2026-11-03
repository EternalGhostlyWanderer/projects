#include "models/items/DockingStation.h"

#include <utility>

DockingStation::DockingStation(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition
)
    : InventoryItem(
          std::move(inventoryNumber),
          std::move(name),
          condition
      ) {}

std::string DockingStation::getKind() const {
    return "Док-станция";
}