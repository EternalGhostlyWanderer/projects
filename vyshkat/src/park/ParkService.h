#pragma once

#include <memory>
#include <string>

#include "inspection/Inspection.h"
#include "interfaces/InspectionService.h"
#include "interfaces/Inventoriable.h"
#include "park/Park.h"

// Фасад над парком: единственный путь добавить объект на баланс.
// Перед приёмкой объект всегда проходит техосмотр.
class ParkService {
public:
    ParkService(Park& park, InspectionService& inspectionService);

    // Объект попадает в парк только при PASSED.
    // Бросает std::invalid_argument для пустого объекта или занятого номера.
    Inspection accept(std::unique_ptr<Inventoriable> item);

    bool removeItem(const std::string& number);

private:
    Park& park_;
    InspectionService& inspectionService_;
};