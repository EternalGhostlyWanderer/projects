#include "models/items/Helmet.h"

#include <stdexcept>
#include <utility>

Helmet::Helmet(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition,
    std::string size
)
    : InventoryItem(
          std::move(inventoryNumber),
          std::move(name),
          condition
      ),
      size_(std::move(size)) {
    if (size_.empty()) {
        throw std::invalid_argument("Размер шлема не может быть пустым");
    }
}

std::string Helmet::getSize() const {
    return size_;
}

std::string Helmet::getKind() const {
    return "Шлем";
}