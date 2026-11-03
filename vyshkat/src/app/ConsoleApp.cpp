#include "app/ConsoleApp.h"

#include <cstddef>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <utility>

#include "app/DemoData.h"

namespace {

std::string formatKwh(double value) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(2) << value;
    return stream.str();
}

void removeAndReport(ParkService& service, const std::string& number) {
    if (service.removeItem(number)) {
        std::cout << "Объект " << number << " удалён из парка.\n";
    } else {
        std::cout << "Объект с номером " << number << " в парке не найден.\n";
    }
}

}  // namespace

ConsoleApp::ConsoleApp(
    ParkService& parkService,
    const ParkReport& parkReport,
    TransportFactory& transportFactory,
    ItemFactory& itemFactory,
    InputReader& input
)
    : parkService_(parkService),
      parkReport_(parkReport),
      transportFactory_(transportFactory),
      itemFactory_(itemFactory),
      input_(input) {}

void ConsoleApp::run()
{
    std::cout << "============================================\n";
    std::cout << "  Добро пожаловать в систему «ВышКат»!\n";
    std::cout << "============================================\n";
    std::cout << "Программа предназначена для учёта парка.\n";
    std::cout << "Здесь можно принимать транспорт и вещи,\n";
    std::cout << "контролировать состояние имущества и\n";
    std::cout << "формировать отчёты по парку.\n\n";
    std::cout << "Выберите действие в меню.\n";
    std::cout << "Для выхода из программы введите 0.\n\n";
    try
    {
        while (true)
        {
            printMenu();

            const int choice = input_.readInt("Ваш выбор: ");

            switch (choice) {
                case 0:
                    std::cout << "Завершение программы.\n";
                    return;
                case 1:
                    handleAddTransport();
                    break;
                case 2:
                    handleAddInventoryItem();
                    break;
                case 3:
                    handleRemoveItem();
                    break;
                case 4:
                    printCounts();
                    break;
                case 5:
                    printEnergyReport();
                    break;
                case 6:
                    printBeginnerList();
                    break;
                case 7:
                    printInventoryList();
                    break;
                case 8:
                    handleDemo();
                    break;
                default:
                    std::cout << "Неизвестная команда. Попробуйте ещё раз.\n";
                    break;
            }
        }
    } catch (const InputEnded&) {
        std::cout << "\nВвод завершён. Завершение программы.\n";
    }
}

void ConsoleApp::printMenu() const {
    std::cout << "\n";
    std::cout << "========== ВышКат ==========\n";
    std::cout << "1. Принять транспорт\n";
    std::cout << "2. Принять вещь\n";
    std::cout << "3. Удалить из парка по инвентарному номеру\n";
    std::cout << "4. Число единиц в парке: всего, транспорт, вещи\n";
    std::cout << "5. Суммарное суточное потребление энергии\n";
    std::cout << "6. Техника, подходящая новичкам\n";
    std::cout << "7. Список техники и вещей с инвентарными номерами\n";
    std::cout << "8. Демонстрационный сценарий\n";
    std::cout << "0. Выход\n";
}

template <typename T>
void ConsoleApp::addFrom(const Factory<T>& factory, const std::string& title) {
    const std::vector<std::string> types = factory.types();
    const int index = chooseType(types, title);

    if (index < 0) {
        return;
    }

    std::unique_ptr<Asset> item;

    try {
        item = factory.create(types[static_cast<std::size_t>(index)], input_);
    } catch (const std::invalid_argument& error) {
        std::cout << "Не удалось создать объект: " << error.what() << "\n";
        return;
    }

    submit(std::move(item));
}

void ConsoleApp::handleAddTransport() {
    addFrom(transportFactory_, "Виды транспорта");
}

void ConsoleApp::handleAddInventoryItem() {
    addFrom(itemFactory_, "Виды вещей");
}

void ConsoleApp::handleRemoveItem() {
    if (parkReport_.countUnits() == 0) {
        std::cout << "Парк пуст, удалять нечего.\n";
        return;
    }

    printInventoryList();

    const std::string number = input_.readString(
        "Инвентарный номер для удаления (Enter - отмена): "
    );

    if (number.empty()) {
        std::cout << "Удаление отменено.\n";
        return;
    }

    removeAndReport(parkService_, number);
}

void ConsoleApp::handleDemo() {
    std::cout << "\n=== Демонстрационный сценарий ===\n";

    std::cout << "\n--- 1. Приёмка: техосмотр пропускает и отклоняет ---\n";

    std::vector<std::unique_ptr<Asset>> assets = makeDemoAssets();

    for (auto& asset : assets) {
        submit(std::move(asset));
    }

    std::cout << "\n--- 2. Отчёты по парку ---\n";
    printCounts();
    printEnergyReport();
    printBeginnerList();
    printInventoryList();

    std::cout << "\n--- 3. Отклонённый объект после ремонта ---\n";
    submit(makeRepairedDemoAsset());

    std::cout << "\n--- 4. Удаление из парка ---\n";
    removeAndReport(parkService_, "CS-001");
    removeAndReport(parkService_, "NO-SUCH-NUMBER");

    std::cout << "\n--- 5. Отчёты после изменений ---\n";
    printCounts();
    printEnergyReport();
    printBeginnerList();
}

void ConsoleApp::printCounts() const {
    std::cout << "Всего на балансе: " << parkReport_.countUnits() << "\n"
              << "  транспорт: " << parkReport_.countTransports() << "\n"
              << "  вещи: " << parkReport_.countInventoryItems() << "\n";
}

void ConsoleApp::printEnergyReport() const {
    std::cout << "Суммарное суточное потребление энергии: "
              << formatKwh(parkReport_.totalDailyEnergyKwh()) << " кВт·ч\n";
}

void ConsoleApp::printBeginnerList() const {
    const auto transports = parkReport_.beginnerFriendly();

    std::cout << "Техника для новичков (простота не ниже "
              << ParkReport::kBeginnerMinSimplicity << "):\n";

    if (transports.empty()) {
        std::cout << "  подходящей техники нет\n";
        return;
    }

    for (const Transport* transport : transports) {
        std::cout << "  " << transport->getInventoryNumber()
                  << " - " << transport->getName()
                  << ", простота " << transport->getSimplicity() << "\n";
    }
}

void ConsoleApp::printInventoryList() const {
    const auto items = parkReport_.listAll();

    std::cout << "Инвентарные номера:\n";

    if (items.empty()) {
        std::cout << "  парк пуст\n";
        return;
    }

    for (const Inventoriable* item : items) {
        std::cout << "  " << item->getInventoryNumber()
                  << " - " << item->getName() << "\n";
    }
}

int ConsoleApp::chooseType(
    const std::vector<std::string>& types,
    const std::string& title
) const {
    if (types.empty()) {
        std::cout << "Нет зарегистрированных видов.\n";
        return -1;
    }

    while (true) {
        std::cout << "\n" << title << ". Выберите вид:\n";

        for (std::size_t i = 0; i < types.size(); ++i) {
            std::cout << i + 1 << ". " << types[i] << "\n";
        }

        std::cout << "0. Назад\n";

        const int choice = input_.readInt("Ваш выбор: ");

        if (choice == 0) {
            return -1;
        }

        if (choice > 0 && choice <= static_cast<int>(types.size())) {
            return choice - 1;
        }

        std::cout << "Нет такого вида. Попробуйте ещё раз.\n";
    }
}

void ConsoleApp::submit(std::unique_ptr<Asset> item) {
    const std::string description = item->getKind() + " \"" +
                                    item->getName() + "\" (" +
                                    item->getInventoryNumber() + ")";

    try {
        const Inspection inspection = parkService_.accept(std::move(item));

        if (inspection.isPassed()) {
            std::cout << description
                      << ": техосмотр пройден, принят в парк.\n";
        } else {
            std::cout << description << ": техосмотр не пройден.\n"
                      << "  Причина: " << inspection.getReason() << "\n"
                      << "  В парк не принят.\n";
        }
    } catch (const std::invalid_argument& error) {
        std::cout << description << ": не принят. " << error.what() << "\n";
    }
}