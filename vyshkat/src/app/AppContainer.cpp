#include "app/AppContainer.h"

#include <stdexcept>
#include <string>
#include <utility>

#include "app/ConsoleApp.h"
#include "enums/EquipmentCondition.h"
#include "inspection/ServiceCenter.h"
#include "models/items/ChargingStation.h"
#include "models/items/DockingStation.h"
#include "models/items/Helmet.h"
#include "models/transport/Bicycle.h"
#include "models/transport/ElectricBicycle.h"
#include "models/transport/ElectricScooter.h"
#include "models/transport/Scooter.h"
#include "park/Park.h"
#include "park/ParkReport.h"
#include "park/ParkService.h"
#include "reader/ConsoleInputReader.h"

namespace {

EquipmentCondition readCondition(InputReader& input) {
    const int choice = input.readInt(
        "Состояние (1 - новое, 2 - хорошее, 3 - требует ремонта, "
        "4 - сломано, 5 - списано): "
    );

    switch (choice) {
        case 1:
            return EquipmentCondition::NEW;
        case 2:
            return EquipmentCondition::GOOD;
        case 3:
            return EquipmentCondition::NEEDS_REPAIR;
        case 4:
            return EquipmentCondition::BROKEN;
        case 5:
            return EquipmentCondition::RETIRED;
        default:
            throw std::invalid_argument("Состояние должно быть числом от 1 до 5");
    }
}

// Данные, общие для всех объектов на балансе.
struct CommonInput {
    std::string inventoryNumber;
    std::string name;
    EquipmentCondition condition;
};

CommonInput readCommon(InputReader& input) {
    const std::string inventoryNumber = input.readString("Инвентарный номер: ");
    const std::string name = input.readString("Название: ");
    const EquipmentCondition condition = readCondition(input);

    return CommonInput{inventoryNumber, name, condition};
}

// Данные, общие для всего транспорта.
struct TransportInput {
    CommonInput common;
    int simplicity;
};

TransportInput readTransport(InputReader& input) {
    const CommonInput common = readCommon(input);
    const int simplicity = input.readInt("Простота для новичка (1-10): ");

    return TransportInput{common, simplicity};
}

}  // namespace

AppContainer::AppContainer() {
    registerServices();
}

DiContainer& AppContainer::services() {
    return container_;
}

void AppContainer::run() {
    container_.resolve<ConsoleApp>()->run();
}

void AppContainer::registerServices() {
    container_.registerType<Park>([](DiContainer&) {
        return std::make_shared<Park>();
    });

    container_.registerType<InspectionService>([](DiContainer&) {
        return std::make_shared<ServiceCenter>();
    });

    container_.registerType<InputReader>([](DiContainer&) {
        return std::make_shared<ConsoleInputReader>();
    });

    container_.registerType<ParkService>([](DiContainer& container) {
        return std::make_shared<ParkService>(
            *container.resolve<Park>(),
            *container.resolve<InspectionService>()
        );
    });

    container_.registerType<ParkReport>([](DiContainer& container) {
        return std::make_shared<ParkReport>(*container.resolve<Park>());
    });

    container_.registerType<TransportFactory>([](DiContainer&) {
        auto factory = std::make_shared<TransportFactory>();
        AppContainer::registerTransportTypes(*factory);
        return factory;
    });

    container_.registerType<ItemFactory>([](DiContainer&) {
        auto factory = std::make_shared<ItemFactory>();
        AppContainer::registerItemTypes(*factory);
        return factory;
    });

    container_.registerType<ConsoleApp>([](DiContainer& container) {
        return std::make_shared<ConsoleApp>(
            *container.resolve<ParkService>(),
            *container.resolve<ParkReport>(),
            *container.resolve<TransportFactory>(),
            *container.resolve<ItemFactory>(),
            *container.resolve<InputReader>()
        );
    });
}

void AppContainer::registerTransportTypes(TransportFactory& factory) {
    factory.registerType("Самокат", [](InputReader& input) {
        const TransportInput data = readTransport(input);

        return std::make_unique<Scooter>(
            data.common.inventoryNumber,
            data.common.name,
            data.common.condition,
            data.simplicity
        );
    });

    factory.registerType("Велосипед", [](InputReader& input) {
        const TransportInput data = readTransport(input);

        return std::make_unique<Bicycle>(
            data.common.inventoryNumber,
            data.common.name,
            data.common.condition,
            data.simplicity
        );
    });

    factory.registerType("Электросамокат", [](InputReader& input) {
        const TransportInput data = readTransport(input);
        const double dailyEnergyKwh =
            input.readDouble("Расход энергии, кВт·ч в сутки: ");

        return std::make_unique<ElectricScooter>(
            data.common.inventoryNumber,
            data.common.name,
            data.common.condition,
            data.simplicity,
            dailyEnergyKwh
        );
    });

    factory.registerType("Электровелосипед", [](InputReader& input) {
        const TransportInput data = readTransport(input);
        const double dailyEnergyKwh =
            input.readDouble("Расход энергии, кВт·ч в сутки: ");

        return std::make_unique<ElectricBicycle>(
            data.common.inventoryNumber,
            data.common.name,
            data.common.condition,
            data.simplicity,
            dailyEnergyKwh
        );
    });
}

void AppContainer::registerItemTypes(ItemFactory& factory) {
    factory.registerType("Шлем", [](InputReader& input) {
        const CommonInput common = readCommon(input);
        const std::string size = input.readString("Размер: ");

        return std::make_unique<Helmet>(
            common.inventoryNumber, common.name, common.condition, size
        );
    });

    factory.registerType("Зарядная станция", [](InputReader& input) {
        const CommonInput common = readCommon(input);
        const double dailyEnergyKwh =
            input.readDouble("Расход энергии, кВт·ч в сутки: ");

        return std::make_unique<ChargingStation>(
            common.inventoryNumber,
            common.name,
            common.condition,
            dailyEnergyKwh
        );
    });

    factory.registerType("Док-станция", [](InputReader& input) {
        const CommonInput common = readCommon(input);

        return std::make_unique<DockingStation>(
            common.inventoryNumber, common.name, common.condition
        );
    });
}