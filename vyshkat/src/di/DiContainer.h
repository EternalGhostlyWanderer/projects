#pragma once

#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <typeindex>
#include <typeinfo>
#include <unordered_map>
#include <utility>

// Минимальный DI-контейнер. Знает, как создать сервис по его типу, и отдаёт
// каждый сервис в единственном экземпляре. Зависимости сервис получает сам:
// создатель просит их у контейнера через resolve().
//
// Замена реализации: повторная регистрация того же типа заменяет прежнюю.
// Делать это нужно до первого resolve() зависимых сервисов.
class DiContainer {
public:
    template <typename T>
    using Creator = std::function<std::shared_ptr<T>(DiContainer&)>;

    // Регистрирует способ создания. Сам объект создаётся при первом resolve().
    template <typename T>
    void registerType(Creator<T> creator) {
        if (!creator) {
            throw std::invalid_argument("Creator cannot be empty");
        }

        Registration registration;
        registration.creator =
            [creator = std::move(creator)](DiContainer& container)
                -> std::shared_ptr<void> {
            return creator(container);
        };

        registrations_[std::type_index(typeid(T))] = std::move(registration);
    }

    // Регистрирует готовый объект (например, заглушку в тесте).
    template <typename T>
    void registerInstance(std::shared_ptr<T> instance) {
        if (!instance) {
            throw std::invalid_argument("Instance cannot be null");
        }

        Registration registration;
        registration.instance = std::move(instance);

        registrations_[std::type_index(typeid(T))] = std::move(registration);
    }

    // Бросает std::logic_error, если тип не зарегистрирован или зависимости
    // образуют цикл.
    template <typename T>
    std::shared_ptr<T> resolve() {
        const auto it = registrations_.find(std::type_index(typeid(T)));

        if (it == registrations_.end()) {
            throw std::logic_error(
                std::string("Service is not registered: ") + typeid(T).name()
            );
        }

        Registration& registration = it->second;

        if (!registration.instance) {
            if (registration.resolving) {
                throw std::logic_error(
                    std::string("Circular dependency: ") + typeid(T).name()
                );
            }

            registration.resolving = true;

            try {
                registration.instance = registration.creator(*this);
            } catch (...) {
                registration.resolving = false;
                throw;
            }

            registration.resolving = false;

            if (!registration.instance) {
                throw std::logic_error(
                    std::string("Creator returned null: ") + typeid(T).name()
                );
            }
        }

        return std::static_pointer_cast<T>(registration.instance);
    }

private:
    struct Registration {
        std::function<std::shared_ptr<void>(DiContainer&)> creator;
        std::shared_ptr<void> instance;
        bool resolving = false;
    };

    std::unordered_map<std::type_index, Registration> registrations_;
};