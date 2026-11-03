#pragma once

#include <string>

#include "enums/EquipmentCondition.h"

class Inventoriable {
public:
    virtual ~Inventoriable() = default;

    virtual std::string getInventoryNumber() const = 0;
    virtual std::string getName() const = 0;
    virtual EquipmentCondition getCondition() const = 0;
};
