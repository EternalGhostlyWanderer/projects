#pragma once

#include <memory>
#include <string>
#include <vector>

#include "factory/ItemFactory.h"
#include "factory/TransportFactory.h"
#include "models/Asset.h"
#include "park/ParkReport.h"
#include "park/ParkService.h"
#include "reader/InputReader.h"

class ConsoleApp {
public:
    ConsoleApp(
        ParkService& parkService,
        const ParkReport& parkReport,
        TransportFactory& transportFactory,
        ItemFactory& itemFactory,
        InputReader& input
    );

    void run();

private:
    ParkService& parkService_;
    const ParkReport& parkReport_;
    TransportFactory& transportFactory_;
    ItemFactory& itemFactory_;
    InputReader& input_;

    void printMenu() const;

    void handleAddTransport();
    void handleAddInventoryItem();
    void handleRemoveItem();
    void handleDemo();

    void printCounts() const;
    void printEnergyReport() const;
    void printBeginnerList() const;
    void printInventoryList() const;

    template <typename T>
    void addFrom(const Factory<T>& factory, const std::string& title);

    // Возвращает индекс выбранного вида или -1, если выбор отменён.
    int chooseType(
        const std::vector<std::string>& types,
        const std::string& title
    ) const;

    // Отправляет объект на приёмку и сообщает результат.
    void submit(std::unique_ptr<Asset> item);
};