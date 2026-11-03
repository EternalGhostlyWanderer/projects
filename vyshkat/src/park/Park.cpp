#include "park/Park.h"

#include <algorithm>
#include <utility>

bool Park::addItem(std::unique_ptr<Inventoriable> item) {
    if (!item) {
        return false;
    }

    if (findByInventoryNumber(item->getInventoryNumber()) != nullptr) {
        return false;
    }

    items_.push_back(std::move(item));
    return true;
}

bool Park::removeByInventoryNumber(const std::string& number) {
    const auto it = std::find_if(
        items_.begin(),
        items_.end(),
        [&number](const std::unique_ptr<Inventoriable>& item) {
            return item->getInventoryNumber() == number;
        }
    );

    if (it == items_.end()) {
        return false;
    }

    items_.erase(it);
    return true;
}

const Inventoriable* Park::findByInventoryNumber(
    const std::string& number
) const {
    const auto it = std::find_if(
        items_.begin(),
        items_.end(),
        [&number](const std::unique_ptr<Inventoriable>& item) {
            return item->getInventoryNumber() == number;
        }
    );

    if (it == items_.end()) {
        return nullptr;
    }

    return it->get();
}

std::vector<const Inventoriable*> Park::all() const {
    std::vector<const Inventoriable*> result;
    result.reserve(items_.size());

    for (const auto& item : items_) {
        result.push_back(item.get());
    }

    return result;
}

std::size_t Park::count() const {
    return items_.size();
}