#include <gtest/gtest.h>

#include <limits>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "support/TestAssets.h"

TEST(TransportTest, StoresConstructorData) {
    const Scooter scooter(
        "SC-1", "City scooter", EquipmentCondition::NEW, 7);

    EXPECT_EQ(scooter.getInventoryNumber(), "SC-1");
    EXPECT_EQ(scooter.getName(), "City scooter");
    EXPECT_TRUE(scooter.getCondition() == EquipmentCondition::NEW);
    EXPECT_EQ(scooter.getSimplicity(), 7);
}

TEST(TransportTest, AcceptsSimplicityBoundaries) {
    EXPECT_NO_THROW(Scooter("A", "n", EquipmentCondition::GOOD, 1));
    EXPECT_NO_THROW(Scooter("A", "n", EquipmentCondition::GOOD, 10));
}

TEST(TransportTest, RejectsSimplicityOutOfRange) {
    EXPECT_THROW(
        Scooter("A", "n", EquipmentCondition::GOOD, 0),
        std::invalid_argument);
    EXPECT_THROW(
        Scooter("A", "n", EquipmentCondition::GOOD, 11),
        std::invalid_argument);
}

TEST(TransportTest, RejectsEmptyFields) {
    EXPECT_THROW(
        Scooter("", "n", EquipmentCondition::GOOD, 5),
        std::invalid_argument);
    EXPECT_THROW(
        Scooter("A", "", EquipmentCondition::GOOD, 5),
        std::invalid_argument);
}

TEST(EnergyTest, ElectricTransportReportsDailyEnergy) {
    const auto scooter = makeElectricScooter("ES-1", 8, 0.6);
    const auto bicycle = makeElectricBicycle("EB-1", 5, 1.2);

    EXPECT_NEAR(scooter->getDailyEnergyKwh(), 0.6, 1e-9);
    EXPECT_NEAR(bicycle->getDailyEnergyKwh(), 1.2, 1e-9);
}

TEST(EnergyTest, RejectsNegativeEnergy) {
    EXPECT_THROW(
        ElectricScooter("A", "n", EquipmentCondition::GOOD, 5, -0.1),
        std::invalid_argument);
    EXPECT_THROW(
        ElectricBicycle("A", "n", EquipmentCondition::GOOD, 5, -0.1),
        std::invalid_argument);
    EXPECT_THROW(
        ChargingStation("A", "n", EquipmentCondition::GOOD, -0.1),
        std::invalid_argument);
}

TEST(EnergyTest, RejectsNonNumericAndInfiniteEnergy) {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();

    EXPECT_THROW(
        ElectricScooter("A", "n", EquipmentCondition::GOOD, 5, nan),
        std::invalid_argument);
    EXPECT_THROW(
        ElectricBicycle("A", "n", EquipmentCondition::GOOD, 5, inf),
        std::invalid_argument);
    EXPECT_THROW(
        ChargingStation("A", "n", EquipmentCondition::GOOD, nan),
        std::invalid_argument);
    EXPECT_THROW(
        ChargingStation("A", "n", EquipmentCondition::GOOD, inf),
        std::invalid_argument);
}

TEST(EnergyTest, ZeroEnergyIsAllowed) {
    EXPECT_NO_THROW(
        ChargingStation("A", "n", EquipmentCondition::GOOD, 0.0));
}

TEST(EnergyTest, OnlyEnergyConsumersExposeTheInterface) {
    EXPECT_TRUE(asConsumer(*makeElectricScooter()) != nullptr);
    EXPECT_TRUE(asConsumer(*makeElectricBicycle()) != nullptr);
    EXPECT_TRUE(asConsumer(*makeChargingStation()) != nullptr);

    EXPECT_TRUE(asConsumer(*makeScooter()) == nullptr);
    EXPECT_TRUE(asConsumer(*makeBicycle()) == nullptr);
    EXPECT_TRUE(asConsumer(*makeHelmet()) == nullptr);
    EXPECT_TRUE(asConsumer(*makeDockingStation()) == nullptr);
}

TEST(ItemTest, HelmetStoresSizeAndRejectsEmptySize) {
    const Helmet helmet("HM-1", "Helmet", EquipmentCondition::GOOD, "L");

    EXPECT_EQ(helmet.getSize(), "L");
    EXPECT_THROW(
        Helmet("HM-2", "Helmet", EquipmentCondition::GOOD, ""),
        std::invalid_argument);
}

TEST(ItemTest, EveryKindHasItsOwnNonEmptyName) {
    std::vector<std::unique_ptr<Asset>> assets;
    assets.push_back(makeScooter());
    assets.push_back(makeBicycle());
    assets.push_back(makeElectricScooter());
    assets.push_back(makeElectricBicycle());
    assets.push_back(makeHelmet());
    assets.push_back(makeChargingStation());
    assets.push_back(makeDockingStation());

    std::set<std::string> kinds;

    for (const auto& asset : assets) {
        EXPECT_FALSE(asset->getKind().empty());
        kinds.insert(asset->getKind());
    }

    EXPECT_EQ(kinds.size(), 7U);
}
TEST(AssetTest, RejectsNegativeNumericInventoryNumber) {
    EXPECT_THROW(
        Scooter("-5", "Test scooter", EquipmentCondition::GOOD, 7),
        std::invalid_argument);
    EXPECT_THROW(
        Scooter("  -5  ", "Test scooter", EquipmentCondition::GOOD, 7),
        std::invalid_argument);
}

TEST(AssetTest, AllowsStringInventoryNumbersAndTrimsSurroundingSpaces) {
    const Scooter scooter(
        "  SC-005  ", "  Test scooter  ", EquipmentCondition::GOOD, 7);

    EXPECT_EQ(scooter.getInventoryNumber(), "SC-005");
    EXPECT_EQ(scooter.getName(), "Test scooter");
}

TEST(AssetTest, RejectsInventoryNumberContainingOnlySpaces) {
    EXPECT_THROW(
        Scooter("   ", "Test scooter", EquipmentCondition::GOOD, 7),
        std::invalid_argument);
}
