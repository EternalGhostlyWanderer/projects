#pragma once

#include <memory>
#include <vector>

#include "models/Asset.h"

// Набор объектов для демонстрационного сценария: есть и те, что пройдут
// техосмотр, и те, что не пройдут, и повтор инвентарного номера.
std::vector<std::unique_ptr<Asset>> makeDemoAssets();

// Тот же электровелосипед EB-002 после ремонта: показывает, что отклонённый
// объект не занимал инвентарный номер.
std::unique_ptr<Asset> makeRepairedDemoAsset();