#include "models/transport/Scooter.h"

#include <utility>

Scooter::Scooter(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition,
    int simplicity
)
    : Transport(
          std::move(inventoryNumber),
          std::move(name),
          condition,
          simplicity
      ) {}

std::string Scooter::getKind() const {
    return "Самокат";
}