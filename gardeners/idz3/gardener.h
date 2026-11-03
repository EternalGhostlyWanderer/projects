#ifndef GARDENER_H
#define GARDENER_H

// Поведение садовника-процесса: маршрут, переходы, обработка клеток.
// Примитивы синхронизации (семафоры) описаны в simulation_internal.h и sync.c.

// Основной цикл садовника id (с 0); возвращает после завершения работы
void gardener_run(int id);

#endif
