#pragma once

#include "interfaces/EnergyConsumer.h"
#include "models/transport/Bicycle.h"

class ElectricBicycle : public Bicycle, public EnergyConsumer {
public:
    ElectricBicycle(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition,
        int simplicity,
        double dailyEnergyKwh
    );

    double getDailyEnergyKwh() const override;
    std::string getKind() const override;

private:
    double dailyEnergyKwh_;
};