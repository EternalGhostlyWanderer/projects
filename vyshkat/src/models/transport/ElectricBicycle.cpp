#include "models/transport/ElectricBicycle.h"

#include <utility>

#include "models/Validation.h"

ElectricBicycle::ElectricBicycle(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition,
    int simplicity,
    double dailyEnergyKwh
)
    : Bicycle(
          std::move(inventoryNumber),
          std::move(name),
          condition,
          simplicity
      ),
      dailyEnergyKwh_(dailyEnergyKwh) {
    requireValidEnergy(dailyEnergyKwh_);
}

double ElectricBicycle::getDailyEnergyKwh() const {
    return dailyEnergyKwh_;
}

std::string ElectricBicycle::getKind() const {
    return "Электровелосипед";
}