#include "models/Asset.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <utility>

namespace {

std::string trim(const std::string& value) {
    const std::size_t first = value.find_first_not_of(" \t\r\n");

    if (first == std::string::npos) {
        return "";
    }

    const std::size_t last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

bool isNegativeIntegerIdentifier(const std::string& value) {
    if (value.size() < 2 || value[0] != '-') {
        return false;
    }

    return std::all_of(value.begin() + 1, value.end(), [](unsigned char ch) {
        return std::isdigit(ch) != 0;
    });
}

}  // namespace

Asset::Asset(
    std::string inventoryNumber,
    std::string name,
    EquipmentCondition condition
)
    : inventoryNumber_(trim(inventoryNumber)),
      name_(trim(name)),
      condition_(condition) {
    if (inventoryNumber_.empty()) {
        throw std::invalid_argument(
            "Инвентарный номер не может быть пустым");
    }

    if (isNegativeIntegerIdentifier(inventoryNumber_)) {
        throw std::invalid_argument(
            "Инвентарный номер не может быть отрицательным числом; "
            "используйте идентификатор, например SC-001"
        );
    }

    if (name_.empty()) {
        throw std::invalid_argument("Название не может быть пустым");
    }
}

std::string Asset::getInventoryNumber() const {
    return inventoryNumber_;
}

std::string Asset::getName() const {
    return name_;
}

EquipmentCondition Asset::getCondition() const {
    return condition_;
}
