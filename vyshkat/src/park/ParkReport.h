#pragma once

#include <cstddef>
#include <vector>

#include "interfaces/Inventoriable.h"
#include "models/transport/Transport.h"
#include "park/Park.h"

// Только чтение: отчёты по содержимому парка.
class ParkReport {
public:
    // Устройство подходит новичку при простоте не ниже этого значения.
    static constexpr int kBeginnerMinSimplicity = 6;

    explicit ParkReport(const Park& park);

    std::size_t countUnits() const;
    std::size_t countTransports() const;
    std::size_t countInventoryItems() const;
    double totalDailyEnergyKwh() const;
    std::vector<const Transport*> beginnerFriendly() const;
    std::vector<const Inventoriable*> listAll() const;

private:
    const Park& park_;
};