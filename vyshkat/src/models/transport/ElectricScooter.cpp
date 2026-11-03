#include "models/transport/ElectricScooter.h"

#include <utility>

#include "models/Validation.h"

ElectricScooter::ElectricScooter(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition,
    int simplicity,
    double dailyEnergyKwh
)
    : Scooter(
          std::move(inventoryNumber),
          std::move(name),
          condition,
          simplicity
      ),
      dailyEnergyKwh_(dailyEnergyKwh) {
    requireValidEnergy(dailyEnergyKwh_);
}

double ElectricScooter::getDailyEnergyKwh() const {
    return dailyEnergyKwh_;
}

std::string ElectricScooter::getKind() const {
    return "Электросамокат";
}