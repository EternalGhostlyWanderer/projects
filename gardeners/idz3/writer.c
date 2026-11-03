#define _GNU_SOURCE
#include "simulation_internal.h"
#include "writer.h"

/* ------------------------------------------------------------------ */
void write_all(int fd, const char *b, size_t n)
{
    while (n > 0) {
        ssize_t k = write(fd, b, n);
        if (k < 0) {
            if (errno == EINTR) continue;
            return;
        }
        if (k == 0) return;
        b += k;
        n -= (size_t)k;
    }
}

/* Вывод одновременно на экран (fd 1) и в лог. */
void out_raw(const char *b, size_t n)
{
    write_all(1, b, n);
    if (log_fd >= 0) write_all(log_fd, b, n);
}

void err_msg(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void err_msg(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf - 1, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 2) n = (int)sizeof buf - 2;
    buf[n++] = '\n';
    write_all(2, buf, (size_t)n);
}

/* Текст причины завершения садовника. */
const char *end_text(int code)
{
    switch (code) {
    case END_NORMAL: return "маршрут пройден";
    case END_SIGNAL: return "прерван сигналом";
    case END_DEADLOCK: return "прерван: тупик";
    case END_INVARIANT: return "прерван: нарушение инварианта";
    case END_LIVELOCK: return "прерван: зацикливание";
    case END_CRASH: return "прерван: аварийное завершение процесса садовника";
    default: return "-";
    }
}

double elapsed(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)(t.tv_sec - t_start.tv_sec) +
           (double)(t.tv_nsec - t_start.tv_nsec) / 1e9;
}

/* Строка без метки времени (итоги, баннер). Только из одного процесса (под мьютексом или до старта). */
void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void say(const char *fmt, ...)
{
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf - 1, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 2) n = (int)sizeof buf - 2;
    buf[n++] = '\n';
    out_raw(buf, (size_t)n);
}

/* Событие с меткой времени. Вызывать при захваченном мьютексе-семафоре —
 * тогда строки разных процессов не перемешиваются и порядок событий согласован с состоянием. */
void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void emit(const char *fmt, ...)
{
    char buf[700];
    int n = snprintf(buf, sizeof buf, "[%7.3f] ", elapsed());
    va_list ap;
    va_start(ap, fmt);
    n += vsnprintf(buf + n, sizeof buf - (size_t)n - 2, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 2) n = (int)sizeof buf - 2;
    buf[n++] = '\n';
    out_raw(buf, (size_t)n);
}

void emit_g(int id, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void emit_g(int id, const char *fmt, ...)
{
    char body[500];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(body, sizeof body, fmt, ap);
    va_end(ap);
    emit("Садовник %d: %s", id + 1, body);
}
