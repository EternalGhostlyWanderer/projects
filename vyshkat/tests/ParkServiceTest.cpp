#include <gtest/gtest.h>

#include <stdexcept>

#include "fakes/FakeInspectionService.h"
#include "inspection/ServiceCenter.h"
#include "park/Park.h"
#include "park/ParkService.h"
#include "support/TestAssets.h"

// Главные тесты на решение техосмотра: ParkService не решает сам,
// решение принимает подставленный InspectionService.
class ParkServiceTest : public ::testing::Test {
protected:
    Park park;
    FakeInspectionService inspection{InspectionResult::PASSED};
    ParkService service{park, inspection};
};

TEST_F(ParkServiceTest, AddsItemWhenInspectionPasses) {
    const Inspection result = service.accept(makeScooter("SC-1"));

    EXPECT_TRUE(result.isPassed());
    EXPECT_EQ(park.count(), 1U);
    EXPECT_TRUE(park.findByInventoryNumber("SC-1") != nullptr);
}

TEST_F(ParkServiceTest, DoesNotAddItemWhenInspectionFails) {
    inspection.setResult(InspectionResult::FAILED);

    const Inspection result = service.accept(makeScooter("SC-1"));

    EXPECT_FALSE(result.isPassed());
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ParkServiceTest, TrustsInspectionAndAcceptsBrokenItemWhenStubPasses) {
    const auto broken = EquipmentCondition::BROKEN;

    EXPECT_TRUE(service.accept(makeScooter("SC-1", 8, broken)).isPassed());
    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ParkServiceTest, TrustsInspectionAndRejectsGoodItemWhenStubFails) {
    inspection.setResult(InspectionResult::FAILED);

    EXPECT_FALSE(service.accept(makeScooter("SC-1")).isPassed());
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ParkServiceTest, InspectsEveryItemExactlyOnce) {
    service.accept(makeScooter("SC-1"));
    service.accept(makeHelmet("HM-1"));

    EXPECT_EQ(inspection.callCount(), 2U);
    EXPECT_EQ(inspection.inspectedNumbers()[0], "SC-1");
    EXPECT_EQ(inspection.inspectedNumbers()[1], "HM-1");
}

TEST_F(ParkServiceTest, InventoryItemsAreInspectedToo) {
    inspection.setResult(InspectionResult::FAILED);

    EXPECT_FALSE(service.accept(makeHelmet("HM-1")).isPassed());
    EXPECT_EQ(inspection.callCount(), 1U);
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ParkServiceTest, RejectedItemDoesNotOccupyItsNumber) {
    inspection.setResult(InspectionResult::FAILED);
    service.accept(makeScooter("SC-1"));

    inspection.setResult(InspectionResult::PASSED);

    EXPECT_TRUE(service.accept(makeScooter("SC-1")).isPassed());
    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ParkServiceTest, DuplicateNumberIsRefusedBeforeInspection) {
    service.accept(makeScooter("SC-1"));

    EXPECT_THROW(service.accept(makeHelmet("SC-1")), std::invalid_argument);
    EXPECT_EQ(inspection.callCount(), 1U);
    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ParkServiceTest, NullItemIsRefused) {
    EXPECT_THROW(service.accept(nullptr), std::invalid_argument);
    EXPECT_EQ(inspection.callCount(), 0U);
}

TEST_F(ParkServiceTest, RemovesAcceptedItem) {
    service.accept(makeScooter("SC-1"));

    EXPECT_TRUE(service.removeItem("SC-1"));
    EXPECT_EQ(park.count(), 0U);
    EXPECT_FALSE(service.removeItem("SC-1"));
}

TEST(ParkServiceWithRealInspectionTest, AcceptsGoodAndRejectsBrokenDevice) {
    Park park;
    ServiceCenter center;
    ParkService service(park, center);

    EXPECT_TRUE(service.accept(makeScooter("SC-1")).isPassed());
    EXPECT_FALSE(service.accept(
        makeScooter("SC-2", 8, EquipmentCondition::BROKEN)).isPassed());
    EXPECT_EQ(park.count(), 1U);
}
