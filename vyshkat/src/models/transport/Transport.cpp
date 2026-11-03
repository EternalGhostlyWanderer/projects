#include "models/transport/Transport.h"

#include <stdexcept>
#include <utility>

Transport::Transport(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition,
    int simplicity
)
    : Asset(
          std::move(inventoryNumber),
          std::move(name),
          condition
      ),
      simplicity_(simplicity) {
    if (simplicity_ < 1 || simplicity_ > 10) {
        throw std::invalid_argument("Простота должна быть от 1 до 10");
    }
}

int Transport::getSimplicity() const {
    return simplicity_;
}