#pragma once

#include "interfaces/EnergyConsumer.h"
#include "models/transport/Scooter.h"

class ElectricScooter : public Scooter, public EnergyConsumer {
public:
    ElectricScooter(
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