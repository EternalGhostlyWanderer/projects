#include <gtest/gtest.h>

#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "factory/ItemFactory.h"
#include "factory/TransportFactory.h"
#include "fakes/FakeInputReader.h"
#include "support/TestAssets.h"

namespace {

std::unique_ptr<Transport> createScooter(InputReader& input) {
    const std::string number = input.readString("");
    const int simplicity = input.readInt("");

    return std::make_unique<Scooter>(
        number, "Scooter", EquipmentCondition::GOOD, simplicity);
}

}  // namespace

class FactoryTest : public ::testing::Test {
protected:
    TransportFactory factory;
};

TEST_F(FactoryTest, CreatesObjectUsingRegisteredCreator) {
    factory.registerType("scooter", createScooter);
    FakeInputReader input({"SC-7", "9"});

    const auto transport = factory.create("scooter", input);

    ASSERT_TRUE(transport != nullptr);
    EXPECT_EQ(transport->getInventoryNumber(), "SC-7");
    EXPECT_EQ(transport->getSimplicity(), 9);
}

TEST_F(FactoryTest, PassesInputReaderToCreator) {
    factory.registerType("scooter", createScooter);
    FakeInputReader input({"SC-7", "9", "unused"});

    factory.create("scooter", input);

    EXPECT_EQ(input.remaining(), 1U);
}

TEST_F(FactoryTest, UnknownTypeIsRefused) {
    FakeInputReader input({});

    EXPECT_THROW(factory.create("nope", input), std::invalid_argument);
}

TEST_F(FactoryTest, DuplicateTypeIsRefused) {
    factory.registerType("scooter", createScooter);

    EXPECT_THROW(
        factory.registerType("scooter", createScooter),
        std::invalid_argument);
}

TEST_F(FactoryTest, EmptyTypeNameIsRefused) {
    EXPECT_THROW(
        factory.registerType("", createScooter),
        std::invalid_argument);
}

TEST_F(FactoryTest, EmptyCreatorIsRefused) {
    EXPECT_THROW(
        factory.registerType("scooter", TransportFactory::CreatorFunction()),
        std::invalid_argument);
}

TEST_F(FactoryTest, ListsTypesInAlphabeticalOrder) {
    factory.registerType("c", createScooter);
    factory.registerType("a", createScooter);
    factory.registerType("b", createScooter);

    const std::vector<std::string> expected = {"a", "b", "c"};

    EXPECT_EQ(factory.types(), expected);
}

TEST_F(FactoryTest, ValidationErrorFromCreatedObjectReachesCaller) {
    factory.registerType("scooter", createScooter);
    FakeInputReader input({"SC-7", "11"});

    EXPECT_THROW(factory.create("scooter", input), std::invalid_argument);
}

TEST_F(FactoryTest, EndOfInputReachesCaller) {
    factory.registerType("scooter", createScooter);
    FakeInputReader input({"SC-7"});

    EXPECT_THROW(factory.create("scooter", input), InputEnded);
}

TEST(ItemFactoryTest, SameTemplateWorksForInventoryItems) {
    ItemFactory factory;
    factory.registerType("helmet", [](InputReader& input) {
        const std::string number = input.readString("");

        return std::make_unique<Helmet>(
            number, "Helmet", EquipmentCondition::GOOD, "M");
    });
    FakeInputReader input({"HM-3"});

    const auto item = factory.create("helmet", input);

    ASSERT_TRUE(item != nullptr);
    EXPECT_EQ(item->getInventoryNumber(), "HM-3");
}