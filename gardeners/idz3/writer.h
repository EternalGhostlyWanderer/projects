#ifndef WRITER_H
#define WRITER_H

#include <stddef.h>

// Запись всего буфера в дескриптор (с повтором при EINTR)
void write_all(int fd, const char *buffer, size_t length);
// Вывод на экран и в журнал
void out_raw(const char *buffer, size_t length);
// Сообщение об ошибке в stderr
void err_msg(const char *format, ...) __attribute__((format(printf, 1, 2)));
// Секунды с начала моделирования
double elapsed(void);
// Строка без метки времени
void say(const char *format, ...) __attribute__((format(printf, 1, 2)));
// Событие с меткой времени (при захваченном мьютексе)
void emit(const char *format, ...) __attribute__((format(printf, 1, 2)));
// Событие садовника с номером (id с 0)
void emit_g(int id, const char *format, ...) __attribute__((format(printf, 2, 3)));

#endif
