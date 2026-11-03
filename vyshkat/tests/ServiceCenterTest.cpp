#include <gtest/gtest.h>

#include "inspection/ServiceCenter.h"
#include "support/TestAssets.h"

class ServiceCenterTest : public ::testing::Test {
protected:
    ServiceCenter center;

    bool transportPasses(EquipmentCondition condition) {
        return center.inspect(*makeScooter("SC-1", 8, condition)).isPassed();
    }
};

TEST_F(ServiceCenterTest, PassesNewDevice) {
    EXPECT_TRUE(transportPasses(EquipmentCondition::NEW));
}

TEST_F(ServiceCenterTest, PassesGoodDevice) {
    EXPECT_TRUE(transportPasses(EquipmentCondition::GOOD));
}

TEST_F(ServiceCenterTest, RejectsDeviceThatNeedsRepair) {
    EXPECT_FALSE(transportPasses(EquipmentCondition::NEEDS_REPAIR));
}

TEST_F(ServiceCenterTest, RejectsBrokenDevice) {
    EXPECT_FALSE(transportPasses(EquipmentCondition::BROKEN));
}

TEST_F(ServiceCenterTest, RejectsRetiredDevice) {
    EXPECT_FALSE(transportPasses(EquipmentCondition::RETIRED));
}

TEST_F(ServiceCenterTest, SameRuleAppliesToInventoryItems) {
    EXPECT_TRUE(center.inspect(*makeDockingStation("DS-1")).isPassed());
    EXPECT_FALSE(center.inspect(
        *makeHelmet("HM-1", EquipmentCondition::BROKEN)).isPassed());
}

TEST(ServiceCenterReasonTest, ExplainsWhyDeviceNeedsRepair) {
    ServiceCenter center;
    const Inspection result = center.inspect(
        *makeScooter("SC-REPAIR", 7, EquipmentCondition::NEEDS_REPAIR));

    EXPECT_FALSE(result.isPassed());
    EXPECT_EQ(result.getReason(), "устройство требует ремонта");
}

TEST(ServiceCenterReasonTest, ExplainsWhyDeviceIsBroken) {
    ServiceCenter center;
    const Inspection result = center.inspect(
        *makeScooter("SC-BROKEN", 7, EquipmentCondition::BROKEN));

    EXPECT_EQ(result.getReason(), "устройство сломано");
}

TEST(ServiceCenterReasonTest, ExplainsWhyDeviceIsRetired) {
    ServiceCenter center;
    const Inspection result = center.inspect(
        *makeScooter("SC-RETIRED", 7, EquipmentCondition::RETIRED));

    EXPECT_EQ(result.getReason(), "устройство списано");
}
