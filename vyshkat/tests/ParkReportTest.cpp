#include <gtest/gtest.h>

#include <algorithm>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "park/Park.h"
#include "park/ParkReport.h"
#include "support/TestAssets.h"

class ParkReportTest : public ::testing::Test {
protected:
    Park park;
    ParkReport report{park};

    void add(std::unique_ptr<Inventoriable> item) {
        ASSERT_TRUE(park.addItem(std::move(item)));
    }

    std::vector<std::string> beginnerNumbers() const {
        std::vector<std::string> numbers;

        for (const Transport* transport : report.beginnerFriendly()) {
            numbers.push_back(transport->getInventoryNumber());
        }

        return numbers;
    }

    bool isBeginnerFriendly(const std::string& number) const {
        const auto numbers = beginnerNumbers();
        return std::find(numbers.begin(), numbers.end(), number) !=
               numbers.end();
    }
};

TEST_F(ParkReportTest, EmptyParkGivesEmptyReports) {
    EXPECT_EQ(report.countUnits(), 0U);
    EXPECT_NEAR(report.totalDailyEnergyKwh(), 0.0, 1e-9);
    EXPECT_TRUE(report.beginnerFriendly().empty());
    EXPECT_TRUE(report.listAll().empty());
}

TEST_F(ParkReportTest, CountsTransportAndItemsTogether) {
    add(makeScooter("SC-1"));
    add(makeElectricBicycle("EB-1"));
    add(makeHelmet("HM-1"));
    add(makeDockingStation("DS-1"));

    EXPECT_EQ(report.countUnits(), 4U);
}

TEST_F(ParkReportTest, CountsTransportAndItemsSeparately) {
    add(makeScooter("SC-1"));
    add(makeElectricBicycle("EB-1"));
    add(makeHelmet("HM-1"));
    add(makeDockingStation("DS-1"));
    add(makeChargingStation("CS-1"));

    EXPECT_EQ(report.countUnits(), 5U);
    EXPECT_EQ(report.countTransports(), 2U);
    EXPECT_EQ(report.countInventoryItems(), 3U);
}

TEST_F(ParkReportTest, SeparateCountsAreZeroForEmptyPark) {
    EXPECT_EQ(report.countTransports(), 0U);
    EXPECT_EQ(report.countInventoryItems(), 0U);
}

TEST_F(ParkReportTest, SeparateCountsFollowRemovals) {
    add(makeScooter("SC-1"));
    add(makeHelmet("HM-1"));

    park.removeByInventoryNumber("HM-1");

    EXPECT_EQ(report.countTransports(), 1U);
    EXPECT_EQ(report.countInventoryItems(), 0U);
}

TEST_F(ParkReportTest, SumsEnergyOfTransportAndChargingStation) {
    add(makeElectricScooter("ES-1", 8, 0.6));
    add(makeElectricBicycle("EB-1", 5, 1.2));
    add(makeChargingStation("CS-1", 3.5));

    EXPECT_NEAR(report.totalDailyEnergyKwh(), 5.3, 1e-9);
}

TEST_F(ParkReportTest, IgnoresDevicesThatConsumeNoEnergy) {
    add(makeScooter("SC-1"));
    add(makeBicycle("BC-1"));
    add(makeHelmet("HM-1"));
    add(makeDockingStation("DS-1"));
    add(makeElectricScooter("ES-1", 8, 0.6));

    EXPECT_NEAR(report.totalDailyEnergyKwh(), 0.6, 1e-9);
}

TEST_F(ParkReportTest, EnergyReflectsRemovedItems) {
    add(makeElectricScooter("ES-1", 8, 0.6));
    add(makeChargingStation("CS-1", 3.5));

    park.removeByInventoryNumber("CS-1");

    EXPECT_NEAR(report.totalDailyEnergyKwh(), 0.6, 1e-9);
}

TEST_F(ParkReportTest, BeginnerThresholdIsSix) {
    EXPECT_EQ(ParkReport::kBeginnerMinSimplicity, 6);
}

TEST_F(ParkReportTest, SimplicitySixIsFriendlyToBeginners) {
    add(makeScooter("SC-6", 6));

    EXPECT_TRUE(isBeginnerFriendly("SC-6"));
}

TEST_F(ParkReportTest, SimplicityFiveIsNotFriendlyToBeginners) {
    add(makeScooter("SC-5", 5));

    EXPECT_FALSE(isBeginnerFriendly("SC-5"));
}

TEST_F(ParkReportTest, SimplicityTenIsFriendlyToBeginners) {
    add(makeBicycle("BC-10", 10));

    EXPECT_TRUE(isBeginnerFriendly("BC-10"));
}

TEST_F(ParkReportTest, BeginnerListContainsOnlySuitableTransport) {
    add(makeScooter("SC-9", 9));
    add(makeElectricScooter("ES-8", 8));
    add(makeElectricBicycle("EB-5", 5));
    add(makeBicycle("BC-4", 4));

    const auto numbers = beginnerNumbers();

    ASSERT_EQ(numbers.size(), 2U);
    EXPECT_TRUE(isBeginnerFriendly("SC-9"));
    EXPECT_TRUE(isBeginnerFriendly("ES-8"));
}

TEST_F(ParkReportTest, ItemsNeverAppearInBeginnerList) {
    add(makeHelmet("HM-1"));
    add(makeChargingStation("CS-1"));
    add(makeDockingStation("DS-1"));

    EXPECT_TRUE(report.beginnerFriendly().empty());
}

TEST_F(ParkReportTest, ListAllShowsNamesAndNumbersOfEverything) {
    add(makeScooter("SC-1"));
    add(makeHelmet("HM-1"));
    add(makeChargingStation("CS-1"));

    const auto items = report.listAll();

    ASSERT_EQ(items.size(), 3U);
    EXPECT_EQ(items[0]->getInventoryNumber(), "SC-1");
    EXPECT_EQ(items[0]->getName(), "Scooter");
    EXPECT_EQ(items[1]->getInventoryNumber(), "HM-1");
    EXPECT_EQ(items[2]->getInventoryNumber(), "CS-1");
}