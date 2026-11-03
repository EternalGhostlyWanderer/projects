#include "models/items/ChargingStation.h"

#include <utility>

#include "models/Validation.h"

ChargingStation::ChargingStation(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition,
    double dailyEnergyKwh
)
    : InventoryItem(
          std::move(inventoryNumber),
          std::move(name),
          condition
      ),
      dailyEnergyKwh_(dailyEnergyKwh) {
    requireValidEnergy(dailyEnergyKwh_);
}

double ChargingStation::getDailyEnergyKwh() const {
    return dailyEnergyKwh_;
}

std::string ChargingStation::getKind() const {
    return "Зарядная станция";
}