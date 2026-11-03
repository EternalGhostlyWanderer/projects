#pragma once

#include <memory>
#include <string>

#include "enums/EquipmentCondition.h"
#include "interfaces/EnergyConsumer.h"
#include "interfaces/Inventoriable.h"
#include "models/items/ChargingStation.h"
#include "models/items/DockingStation.h"
#include "models/items/Helmet.h"
#include "models/transport/Bicycle.h"
#include "models/transport/ElectricBicycle.h"
#include "models/transport/ElectricScooter.h"
#include "models/transport/Scooter.h"

// Короткие построители тестовых объектов. По умолчанию объект исправен.

inline std::unique_ptr<Scooter> makeScooter(
    const std::string& number = "SC-1",
    int simplicity = 8,
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<Scooter>(
        number, "Scooter", condition, simplicity);
}

inline std::unique_ptr<Bicycle> makeBicycle(
    const std::string& number = "BC-1",
    int simplicity = 8,
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<Bicycle>(
        number, "Bicycle", condition, simplicity);
}

inline std::unique_ptr<ElectricScooter> makeElectricScooter(
    const std::string& number = "ES-1",
    int simplicity = 8,
    double dailyEnergyKwh = 0.6,
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<ElectricScooter>(
        number, "Electric scooter", condition, simplicity,
        dailyEnergyKwh);
}

inline std::unique_ptr<ElectricBicycle> makeElectricBicycle(
    const std::string& number = "EB-1",
    int simplicity = 5,
    double dailyEnergyKwh = 1.2,
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<ElectricBicycle>(
        number, "Electric bicycle", condition, simplicity,
        dailyEnergyKwh);
}

inline std::unique_ptr<Helmet> makeHelmet(
    const std::string& number = "HM-1",
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<Helmet>(number, "Helmet", condition, "M");
}

inline std::unique_ptr<ChargingStation> makeChargingStation(
    const std::string& number = "CS-1",
    double dailyEnergyKwh = 3.5,
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<ChargingStation>(
        number, "Charging station", condition, dailyEnergyKwh);
}

inline std::unique_ptr<DockingStation> makeDockingStation(
    const std::string& number = "DS-1",
    EquipmentCondition condition = EquipmentCondition::GOOD
) {
    return std::make_unique<DockingStation>(number, "Docking station", condition);
}

// Потребляет ли объект энергию (так же, как это делает ParkReport).
inline const EnergyConsumer* asConsumer(const Inventoriable& item) {
    return dynamic_cast<const EnergyConsumer*>(&item);
}