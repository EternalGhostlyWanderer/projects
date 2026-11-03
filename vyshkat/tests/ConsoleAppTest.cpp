#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "app/ConsoleApp.h"
#include "fakes/FakeInputReader.h"
#include "inspection/ServiceCenter.h"
#include "park/Park.h"
#include "park/ParkReport.h"
#include "park/ParkService.h"
#include "support/CoutCapture.h"
#include "support/TestAssets.h"

// Сценарии консоли: ввод подменяется FakeInputReader, вывод перехватывается.
// Пункты меню: 1 - принять транспорт, 2 - принять вещь, 3 - удалить,
// 8 - демонстрация, 0 - выход.
namespace {

std::size_t countOccurrences(const std::string& text, const std::string& part) {
    std::size_t count = 0;
    std::size_t position = text.find(part);

    while (position != std::string::npos) {
        ++count;
        position = text.find(part, position + part.size());
    }

    return count;
}

}  // namespace

class ConsoleAppTest : public ::testing::Test {
protected:
    Park park;
    ServiceCenter center;
    ParkService service{park, center};
    ParkReport report{park};
    TransportFactory transports;
    ItemFactory items;

    void SetUp() override {
        transports.registerType("scooter", [](InputReader& input) {
            const std::string number = input.readString("");
            const int simplicity = input.readInt("");

            return std::make_unique<Scooter>(
                number, "Scooter", EquipmentCondition::GOOD,
                simplicity);
        });

        // Этот шлем всегда сломан: техосмотр должен его отклонить.
        items.registerType("broken helmet", [](InputReader& input) {
            const std::string number = input.readString("");

            return std::make_unique<Helmet>(
                number, "Helmet", EquipmentCondition::BROKEN, "M");
        });
    }

    std::string run(std::vector<std::string> answers) {
        FakeInputReader input(std::move(answers));
        ConsoleApp app(service, report, transports, items, input);
        CoutCapture capture;

        app.run();

        return capture.str();
    }
};

TEST_F(ConsoleAppTest, ExitsOnZero) {
    EXPECT_NO_THROW(run({"0"}));
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, ExitsQuietlyWhenInputEnds) {
    EXPECT_NO_THROW(run({}));
}

TEST_F(ConsoleAppTest, ExitsQuietlyWhenInputEndsInsideScenario) {
    EXPECT_NO_THROW(run({"1", "1", "SC-1"}));
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, UnknownMenuItemChangesNothing) {
    EXPECT_NO_THROW(run({"99", "0"}));
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, AcceptsTransportThatPassesInspection) {
    run({"1", "1", "SC-1", "8", "0"});

    EXPECT_EQ(park.count(), 1U);
    EXPECT_TRUE(park.findByInventoryNumber("SC-1") != nullptr);
}

TEST_F(ConsoleAppTest, InventoryItemIsInspectedAndRejectedWhenBroken) {
    run({"2", "1", "HM-1", "0"});

    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, InvalidDataDoesNotCrashAndAddsNothing) {
    EXPECT_NO_THROW(run({"1", "1", "SC-1", "11", "0"}));
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, DuplicateInventoryNumberIsRefused) {
    run({"1", "1", "SC-1", "8", "1", "1", "SC-1", "8", "0"});

    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ConsoleAppTest, OutOfRangeTypeChoiceShowsMenuAgain) {
    const std::string output = run({"1", "7", "1", "SC-1", "8", "0"});

    EXPECT_EQ(park.count(), 1U);
    EXPECT_NE(
        output.find("Нет такого вида. Попробуйте ещё раз."),
        std::string::npos
    );
    EXPECT_GE(countOccurrences(output, "Выберите вид:"), 2U);
}

TEST_F(ConsoleAppTest, ShowsReasonWhenInspectionRejectsItem) {
    const std::string output = run({"2", "1", "HM-1", "0"});

    EXPECT_NE(
        output.find("техосмотр не пройден"),
        std::string::npos
    );
    EXPECT_NE(
        output.find("Причина: устройство сломано"),
        std::string::npos
    );
    EXPECT_NE(
        output.find("В парк не принят"),
        std::string::npos
    );
}
TEST_F(ConsoleAppTest, BackFromTypeListChangesNothing) {
    EXPECT_NO_THROW(run({"1", "0", "0"}));
    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, RemovesItemByInventoryNumber) {
    run({"1", "1", "SC-1", "8", "3", "SC-1", "0"});

    EXPECT_EQ(park.count(), 0U);
}

TEST_F(ConsoleAppTest, RemovingMissingItemIsHarmless) {
    run({"1", "1", "SC-1", "8", "3", "NOPE", "0"});

    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ConsoleAppTest, EmptyEnterCancelsRemoval) {
    const std::string output = run({"1", "1", "SC-1", "8", "3", "", "0"});

    EXPECT_EQ(park.count(), 1U);
    // Отмена не должна выглядеть как неудачный поиск объекта.
    EXPECT_TRUE(output.find("не найден") == std::string::npos);
}

TEST_F(ConsoleAppTest, RemovalShowsParkContentsBeforeAskingForNumber) {
    // Номер SC-1 печатается при приёмке один раз и ещё раз в списке перед удалением.
    const std::string output = run({"1", "1", "SC-1", "8", "3", "", "0"});

    EXPECT_TRUE(countOccurrences(output, "SC-1") >= 2U);
}

TEST_F(ConsoleAppTest, RemovalFromEmptyParkDoesNotAskForNumber) {
    FakeInputReader input({"3", "0", "unused"});
    ConsoleApp app(service, report, transports, items, input);
    CoutCapture capture;

    app.run();

    EXPECT_EQ(input.remaining(), 1U);
}

TEST_F(ConsoleAppTest, ReportsDoNotChangeThePark) {
    run({"1", "1", "SC-1", "8", "4", "5", "6", "7", "0"});

    EXPECT_EQ(park.count(), 1U);
}

TEST_F(ConsoleAppTest, BeginnerListShowsSuitableTransport) {
    const std::string output = run({"1", "1", "SC-1", "8", "6", "0"});

    EXPECT_TRUE(output.find("SC-1") != std::string::npos);
}

TEST_F(ConsoleAppTest, InventoryListShowsNumbers) {
    const std::string output = run({"1", "1", "SC-1", "3", "7", "0"});

    EXPECT_TRUE(output.find("SC-1") != std::string::npos);
}

TEST_F(ConsoleAppTest, DemoRejectsEveryKindOfBadItem) {
    run({"8", "0"});

    EXPECT_TRUE(park.findByInventoryNumber("HM-002") == nullptr);  // списан
    EXPECT_TRUE(park.findByInventoryNumber("SC-002") == nullptr);  // нужен ремонт
}

TEST_F(ConsoleAppTest, DemoAcceptsRejectedItemAgainAfterRepair) {
    run({"8", "0"});

    const Inventoriable* repaired = park.findByInventoryNumber("EB-002");

    ASSERT_TRUE(repaired != nullptr);
    EXPECT_TRUE(repaired->getCondition() == EquipmentCondition::GOOD);
}

TEST_F(ConsoleAppTest, DemoRemovesChargingStation) {
    run({"8", "0"});

    EXPECT_TRUE(park.findByInventoryNumber("CS-001") == nullptr);
    EXPECT_EQ(park.count(), 8U);
}

TEST_F(ConsoleAppTest, DemoShowsEnergyBeforeAndAfterChanges) {
    const std::string output = run({"8", "0"});

    EXPECT_TRUE(output.find("5.30") != std::string::npos);
    EXPECT_TRUE(output.find("3.00") != std::string::npos);
}

TEST_F(ConsoleAppTest, DemoShowsInventoryNumbers) {
    const std::string output = run({"8", "0"});

    EXPECT_TRUE(output.find("SC-001") != std::string::npos);
    EXPECT_TRUE(output.find("CS-001") != std::string::npos);
}

TEST_F(ConsoleAppTest, DemoPicksThreeTransportsForBeginnersIncludingBoundary) {
    run({"8", "0"});

    const auto beginnerTransports = report.beginnerFriendly();

    ASSERT_EQ(beginnerTransports.size(), 3U);
    // BC-002 имеет простоту ровно 6: граница правила.
    bool boundaryIncluded = false;

    for (const Transport* transport : beginnerTransports) {
        if (transport->getInventoryNumber() == "BC-002") {
            boundaryIncluded = true;
        }
    }

    EXPECT_TRUE(boundaryIncluded);
}

TEST_F(ConsoleAppTest, DemoSplitsCountsIntoTransportAndItems) {
    run({"8", "0"});

    EXPECT_EQ(report.countTransports(), 6U);
    EXPECT_EQ(report.countInventoryItems(), 2U);
}

TEST_F(ConsoleAppTest, DemoCanBeRunTwiceWithoutDuplicates) {
    EXPECT_NO_THROW(run({"8", "8", "0"}));
    EXPECT_EQ(park.count(), 8U);
}