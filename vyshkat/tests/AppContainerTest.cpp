#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <vector>

#include "app/AppContainer.h"
#include "app/ConsoleApp.h"
#include "fakes/FakeInputReader.h"
#include "fakes/FakeInspectionService.h"
#include "park/Park.h"
#include "park/ParkReport.h"
#include "park/ParkService.h"
#include "support/TestAssets.h"

// Проверка DI: рабочая сборка и подмена техосмотра через контейнер.
class AppContainerTest : public ::testing::Test {
protected:
    AppContainer app;
};

TEST_F(AppContainerTest, DefaultWiringUsesRealInspection) {
    const auto service = app.services().resolve<ParkService>();

    EXPECT_TRUE(service->accept(makeScooter("SC-1")).isPassed());
    EXPECT_FALSE(service->accept(
        makeScooter("SC-2", 8, EquipmentCondition::BROKEN)).isPassed());
    EXPECT_EQ(app.services().resolve<Park>()->count(), 1U);
}

TEST_F(AppContainerTest, StubReplacesInspectionAndRejectsGoodItem) {
    const auto stub =
        std::make_shared<FakeInspectionService>(InspectionResult::FAILED);
    app.services().registerInstance<InspectionService>(stub);

    const auto service = app.services().resolve<ParkService>();

    EXPECT_FALSE(service->accept(makeScooter("SC-1")).isPassed());
    EXPECT_EQ(stub->callCount(), 1U);
    EXPECT_EQ(app.services().resolve<Park>()->count(), 0U);
}

TEST_F(AppContainerTest, StubReplacesInspectionAndAcceptsBrokenItem) {
    const auto stub =
        std::make_shared<FakeInspectionService>(InspectionResult::PASSED);
    app.services().registerInstance<InspectionService>(stub);

    const auto service = app.services().resolve<ParkService>();

    EXPECT_TRUE(service->accept(
        makeScooter("SC-1", 8, EquipmentCondition::BROKEN)).isPassed());
    EXPECT_EQ(app.services().resolve<Park>()->count(), 1U);
}

TEST_F(AppContainerTest, ServiceAndReportShareOnePark) {
    const auto service = app.services().resolve<ParkService>();
    const auto report = app.services().resolve<ParkReport>();

    service->accept(makeElectricScooter("ES-1", 8, 0.6));

    EXPECT_EQ(report->countUnits(), 1U);
    EXPECT_NEAR(report->totalDailyEnergyKwh(), 0.6, 1e-9);
}

TEST_F(AppContainerTest, AllServicesCanBeResolved) {
    EXPECT_TRUE(app.services().resolve<ConsoleApp>() != nullptr);
    EXPECT_TRUE(app.services().resolve<InputReader>() != nullptr);
}

TEST_F(AppContainerTest, EveryRegisteredTransportTypeCanBeCreated) {
    const auto factory = app.services().resolve<TransportFactory>();
    const auto types = factory->types();

    EXPECT_EQ(types.size(), 4U);

    int energyConsumers = 0;

    for (const std::string& type : types) {
        FakeInputReader input({"T-1", "Name", "2", "8", "1.5"});

        const auto transport = factory->create(type, input);

        ASSERT_TRUE(transport != nullptr);
        EXPECT_EQ(transport->getInventoryNumber(), "T-1");
        EXPECT_EQ(transport->getSimplicity(), 8);

        if (asConsumer(*transport) != nullptr) {
            ++energyConsumers;
        }
    }

    EXPECT_EQ(energyConsumers, 2);
}

TEST_F(AppContainerTest, EveryRegisteredItemTypeCanBeCreated) {
    const auto factory = app.services().resolve<ItemFactory>();
    const auto types = factory->types();

    EXPECT_EQ(types.size(), 3U);

    int energyConsumers = 0;

    for (const std::string& type : types) {
        FakeInputReader input({"I-1", "Name", "2", "1.5"});

        const auto item = factory->create(type, input);

        ASSERT_TRUE(item != nullptr);
        EXPECT_EQ(item->getInventoryNumber(), "I-1");

        if (asConsumer(*item) != nullptr) {
            ++energyConsumers;
        }
    }

    EXPECT_EQ(energyConsumers, 1);
}

TEST_F(AppContainerTest, CreatorRejectsUnknownCondition) {
    const auto factory = app.services().resolve<TransportFactory>();
    const auto types = factory->types();
    FakeInputReader input({"T-1", "Name", "9"});

    EXPECT_THROW(factory->create(types.front(), input), std::invalid_argument);
}

TEST_F(AppContainerTest, EveryConditionNumberIsAccepted) {
    const auto factory = app.services().resolve<ItemFactory>();
    const auto types = factory->types();

    for (const std::string number : {"1", "2", "3", "4", "5"}) {
        FakeInputReader input({"I-1", "Name", number, "1.5"});

        EXPECT_NO_THROW(factory->create(types.front(), input));
    }
}