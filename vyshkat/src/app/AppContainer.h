#pragma once

#include "di/DiContainer.h"
#include "factory/ItemFactory.h"
#include "factory/TransportFactory.h"

// Composition root: регистрирует рабочие реализации в DI-контейнере и
// запускает приложение. Любой сервис можно заменить через services()
// до первого resolve() зависимых сервисов (так в тестах подменяется техосмотр).
class AppContainer {
public:
    AppContainer();

    AppContainer(const AppContainer&) = delete;
    AppContainer& operator=(const AppContainer&) = delete;

    DiContainer& services();

    void run();

private:
    DiContainer container_;

    void registerServices();
    static void registerTransportTypes(TransportFactory& factory);
    static void registerItemTypes(ItemFactory& factory);
};