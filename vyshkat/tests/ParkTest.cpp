#include <gtest/gtest.h>

#include <memory>
#include <utility>

#include "park/Park.h"
#include "support/TestAssets.h"

class ParkTest : public ::testing::Test {
protected:
    Park park;
};

TEST_F(ParkTest, StartsEmpty) {
    EXPECT_EQ(park.count(), 0U);
    EXPECT_TRUE(park.all().empty());
}

TEST_F(ParkTest, AddsItem) {
    EXPECT_TRUE(park.addItem(makeScooter("SC-1")));

    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ParkTest, RejectsDuplicateInventoryNumber) {
    ASSERT_TRUE(park.addItem(makeScooter("SC-1")));

    EXPECT_FALSE(park.addItem(makeHelmet("SC-1")));
    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ParkTest, RejectsNullItem) {
    EXPECT_FALSE(park.addItem(nullptr));
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ParkTest, FindsItemByInventoryNumber) {
    park.addItem(makeScooter("SC-1"));
    park.addItem(makeHelmet("HM-1"));

    const Inventoriable* found = park.findByInventoryNumber("HM-1");

    ASSERT_TRUE(found != nullptr);
    EXPECT_EQ(found->getInventoryNumber(), "HM-1");
}

TEST_F(ParkTest, ReturnsNullWhenItemIsMissing) {
    EXPECT_TRUE(park.findByInventoryNumber("NOPE") == nullptr);
}

TEST_F(ParkTest, RemovesItem) {
    park.addItem(makeScooter("SC-1"));

    EXPECT_TRUE(park.removeByInventoryNumber("SC-1"));
    EXPECT_EQ(park.count(), 0U);
    EXPECT_TRUE(park.findByInventoryNumber("SC-1") == nullptr);
}

TEST_F(ParkTest, RemovingMissingItemReturnsFalse) {
    park.addItem(makeScooter("SC-1"));

    EXPECT_FALSE(park.removeByInventoryNumber("NOPE"));
    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ParkTest, FreedNumberCanBeUsedAgain) {
    park.addItem(makeScooter("SC-1"));
    park.removeByInventoryNumber("SC-1");

    EXPECT_TRUE(park.addItem(makeHelmet("SC-1")));
}

TEST_F(ParkTest, ListsItemsInInsertionOrder) {
    park.addItem(makeScooter("SC-1"));
    park.addItem(makeHelmet("HM-1"));
    park.addItem(makeDockingStation("DS-1"));

    const auto items = park.all();

    ASSERT_EQ(items.size(), 3U);
    EXPECT_EQ(items[0]->getInventoryNumber(), "SC-1");
    EXPECT_EQ(items[1]->getInventoryNumber(), "HM-1");
    EXPECT_EQ(items[2]->getInventoryNumber(), "DS-1");
}
