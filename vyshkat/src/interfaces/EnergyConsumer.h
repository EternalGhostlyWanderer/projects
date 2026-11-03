#pragma once

class EnergyConsumer {
public:
    virtual ~EnergyConsumer() = default;

    virtual double getDailyEnergyKwh() const = 0;
};