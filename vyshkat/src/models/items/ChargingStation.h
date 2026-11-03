#pragma once

#include <string>

#include "interfaces/EnergyConsumer.h"
#include "models/items/InventoryItem.h"

class ChargingStation : public InventoryItem, public EnergyConsumer {
public:
    ChargingStation(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition,
        double dailyEnergyKwh
    );

    double getDailyEnergyKwh() const override;
    std::string getKind() const override;

private:
    double dailyEnergyKwh_;
};