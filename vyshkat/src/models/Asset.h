#pragma once

#include <string>

#include "enums/EquipmentCondition.h"
#include "interfaces/Inventoriable.h"

class Asset : public Inventoriable {
public:
    Asset(
        std::string inventoryNumber,
        std::string name,
        EquipmentCondition condition
    );

    ~Asset() override = default;

    std::string getInventoryNumber() const override;
    std::string getName() const override;
    EquipmentCondition getCondition() const override;

    virtual std::string getKind() const = 0;

protected:
    std::string inventoryNumber_;
    std::string name_;
    EquipmentCondition condition_;
};
