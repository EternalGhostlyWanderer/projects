#include <exception>
#include <iostream>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#else
#include <signal.h>
#endif

#include "app/AppContainer.h"

namespace {

// Включает UTF-8 для ввода и вывода консоли Windows.
// На других системах ничего не делает.
void setupConsoleUtf8() {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
#endif
}

#ifdef _WIN32

// В Windows Ctrl+C завершает процесс средствами системы. Данные хранятся
// только в памяти, сохранять нечего.
void setupInterruptHandler() {}

#else

// Обработчик ничего не делает: ему достаточно существовать, чтобы Ctrl+C
// прервал ожидание ввода ошибкой чтения, а не убил процесс. Дальше работает
// обычный путь конца ввода (InputEnded) и программа завершается штатно.
// SA_RESETHAND возвращает стандартное поведение, поэтому повторный Ctrl+C
// завершает программу немедленно.
void onInterrupt(int) {}

void setupInterruptHandler() {
    struct sigaction action {};
    action.sa_handler = onInterrupt;
    sigemptyset(&action.sa_mask);
    action.sa_flags = SA_RESETHAND;
    sigaction(SIGINT, &action, nullptr);
}

#endif

}  // namespace

int main() {
    setupConsoleUtf8();
    setupInterruptHandler();

    try {
        AppContainer container;
        container.run();
    } catch (const std::exception& error) {
        std::cerr << "Критическая ошибка: " << error.what() << "\n";
        return 1;
    }

    return 0;
}