#include "inspection/ServiceCenter.h"

#include "enums/EquipmentCondition.h"
#include "enums/InspectionResult.h"

Inspection ServiceCenter::inspect(const Inventoriable& item) {
    if (isAllowed(item)) {
        return Inspection(InspectionResult::PASSED);
    }

    return Inspection(InspectionResult::FAILED, rejectionReason(item));
}

bool ServiceCenter::isAllowed(const Inventoriable& item) const {
    const EquipmentCondition condition = item.getCondition();

    return condition == EquipmentCondition::NEW ||
           condition == EquipmentCondition::GOOD;
}

std::string ServiceCenter::rejectionReason(const Inventoriable& item) const {
    switch (item.getCondition()) {
        case EquipmentCondition::NEEDS_REPAIR:
            return "устройство требует ремонта";
        case EquipmentCondition::BROKEN:
            return "устройство сломано";
        case EquipmentCondition::RETIRED:
            return "устройство списано";
        case EquipmentCondition::NEW:
        case EquipmentCondition::GOOD:
            break;
    }

    return "состояние устройства не позволяет принять его "
           "в парк";
}
