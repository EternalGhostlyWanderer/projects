#include "park/ParkReport.h"

#include "interfaces/EnergyConsumer.h"

ParkReport::ParkReport(const Park& park) : park_(park) {}

std::size_t ParkReport::countUnits() const {
    return park_.count();
}

std::size_t ParkReport::countTransports() const {
    std::size_t count = 0;

    for (const Inventoriable* item : park_.all()) {
        if (dynamic_cast<const Transport*>(item) != nullptr) {
            ++count;
        }
    }

    return count;
}

std::size_t ParkReport::countInventoryItems() const {
    return countUnits() - countTransports();
}

double ParkReport::totalDailyEnergyKwh() const {
    double total = 0.0;

    for (const Inventoriable* item : park_.all()) {
        const auto* consumer = dynamic_cast<const EnergyConsumer*>(item);

        if (consumer != nullptr) {
            total += consumer->getDailyEnergyKwh();
        }
    }

    return total;
}

std::vector<const Transport*> ParkReport::beginnerFriendly() const {
    std::vector<const Transport*> result;

    for (const Inventoriable* item : park_.all()) {
        const auto* transport = dynamic_cast<const Transport*>(item);

        if (transport != nullptr &&
            transport->getSimplicity() >= kBeginnerMinSimplicity) {
            result.push_back(transport);
        }
    }

    return result;
}

std::vector<const Inventoriable*> ParkReport::listAll() const {
    return park_.all();
}