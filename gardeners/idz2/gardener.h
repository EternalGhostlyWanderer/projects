#ifndef GARDENER_H
#define GARDENER_H

// Создаёт примитивы синхронизации и уничтожает их
void prims_init(void);
void prims_destroy(void);
// Захватывает клетку без ожидания; 1 — успех
int cell_try(int gardener_id, int cell);
// Ждёт клетку не дольше указанного времени; 1 — клетка захвачена
int cell_wait_slice(int gardener_id, int cell, int milliseconds);
// Освобождает клетку
void cell_release(int gardener_id, int cell);
// Общий старт потоков: открыть и ждать
void start_open(void);
void start_wait(void);
// Сообщение главному потоку о завершении садовника и ожидание такого сообщения
void done_signal(void);
int done_wait_slice(int milliseconds);
// Функция потока садовника
void *gardener_main(void *arg);

#endif
