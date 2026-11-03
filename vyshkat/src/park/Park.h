#pragma once

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "interfaces/Inventoriable.h"

// Хранилище объектов на балансе. Владеет ими и следит за уникальностью
// инвентарного номера. Решений о приёмке не принимает.
class Park {
public:
    // false, если объект пустой или его номер уже занят.
    bool addItem(std::unique_ptr<Inventoriable> item);

    bool removeByInventoryNumber(const std::string& number);

    // nullptr, если объекта с таким номером нет.
    const Inventoriable* findByInventoryNumber(const std::string& number) const;

    std::vector<const Inventoriable*> all() const;

    std::size_t count() const;

private:
    std::vector<std::unique_ptr<Inventoriable>> items_;
};