#pragma once

#include <algorithm>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "reader/InputReader.h"

// Фабрика с реестром создателей (Factory Method).
// T - базовый тип создаваемых объектов (Transport, InventoryItem, ...).
template <typename T>
class Factory {
public:
    using CreatorFunction = std::function<std::unique_ptr<T>(InputReader&)>;

    void registerType(const std::string& type, CreatorFunction creator) {
        if (type.empty()) {
            throw std::invalid_argument("Название вида не может быть пустым");
        }

        if (!creator) {
            throw std::invalid_argument("Создатель вида не задан");
        }

        if (!creators_.emplace(type, std::move(creator)).second) {
            throw std::invalid_argument(
                "Вид уже зарегистрирован: " + type
            );
        }
    }

    std::unique_ptr<T> create(
        const std::string& type,
        InputReader& input
    ) const {
        const auto it = creators_.find(type);

        if (it == creators_.end()) {
            throw std::invalid_argument("Неизвестный вид: " + type);
        }

        return it->second(input);
    }

    // Виды в алфавитном порядке, чтобы меню было стабильным.
    std::vector<std::string> types() const {
        std::vector<std::string> result;
        result.reserve(creators_.size());

        for (const auto& entry : creators_) {
            result.push_back(entry.first);
        }

        std::sort(result.begin(), result.end());
        return result;
    }

private:
    std::unordered_map<std::string, CreatorFunction> creators_;
};