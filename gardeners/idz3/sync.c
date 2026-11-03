#define _GNU_SOURCE
#include "simulation_internal.h"
#include "shared.h"

/* Семафоры текущего процесса. В именованном режиме указатели получены
 * из sem_open(), в неименованном — указывают на sem_t внутри shm. */
static sem_t *mtx_s, *start_s, *ready_s, *done_s;
static sem_t *cell_s[MAX_CELLS];
static char base_name[96];
static int n_cells;                  /* сколько семафоров клеток создано/открыто */
static pid_t creator_pid;            /* процесс, создавший семафоры */

/* В версии с очередью сообщений клетками распоряжается процесс-сервер,
 * поэтому семафоры клеток не нужны. */
#ifdef IPC_MQ
#define CELLSEMS 0
#else
#define CELLSEMS NC
#endif

/* Дополнительная очистка при аварийном выходе (очереди сообщений). */
void (*ipc_extra_cleanup)(void) = NULL;

#if defined(SEM_UNNAMED) && !defined(INDEPENDENT) && !defined(IPC_MQ)
#define UNNAMED 1
#else
#define UNNAMED 0
#endif

static void abs_deadline(struct timespec *ts, int ms)
{
    clock_gettime(CLOCK_REALTIME, ts);
    ts->tv_sec += ms / 1000;
    ts->tv_nsec += (long)(ms % 1000) * 1000000L;
    if (ts->tv_nsec >= 1000000000L) {
        ts->tv_nsec -= 1000000000L;
        ts->tv_sec++;
    }
}

#if !UNNAMED
static void sem_name(char *out, size_t n, const char *suffix, int idx)
{
    if (idx >= 0) snprintf(out, n, "%s_%s%d", base_name, suffix, idx);
    else snprintf(out, n, "%s_%s", base_name, suffix);
}

static sem_t *open_new(const char *suffix, int idx, unsigned init)
{
    char nm[128];
    sem_name(nm, sizeof nm, suffix, idx);
    sem_unlink(nm); /* остаток после аварийного завершения */
    sem_t *s = sem_open(nm, O_CREAT | O_EXCL, 0600, init);
    return s == SEM_FAILED ? NULL : s;
}

static sem_t *open_existing(const char *suffix, int idx)
{
    char nm[128];
    sem_name(nm, sizeof nm, suffix, idx);
    sem_t *s = sem_open(nm, 0);
    return s == SEM_FAILED ? NULL : s;
}

#endif

/* Создание всех семафоров (родитель или garden_init). */
int prims_create(const char *base)
{
    snprintf(base_name, sizeof base_name, "%s", base);
    creator_pid = getpid();
    n_cells = 0;
#if UNNAMED
    sem_init(&S->u_mtx, 1, 1);
    sem_init(&S->u_start, 1, 0);
    sem_init(&S->u_ready, 1, 0);
    sem_init(&S->u_done, 1, 0);
    mtx_s = &S->u_mtx;
    start_s = &S->u_start;
    ready_s = &S->u_ready;
    done_s = &S->u_done;
    for (int i = 0; i < NC; i++) {
        sem_init(&S->u_cell[i], 1, 1);
        cell_s[i] = &S->u_cell[i];
    }
    n_cells = NC;
    return 1;
#else
    mtx_s = open_new("m", -1, 1);
    start_s = open_new("s", -1, 0);
    ready_s = open_new("r", -1, 0);
    done_s = open_new("d", -1, 0);
    if (!mtx_s || !start_s || !ready_s || !done_s) {
        err_msg("sem_open: %s", strerror(errno));
        prims_unlink();
        return 0;
    }
    for (int i = 0; i < CELLSEMS; i++) {
        cell_s[i] = open_new("c", i, 1);
        if (!cell_s[i]) {
            err_msg("sem_open(клетка %d): %s", i, strerror(errno));
            prims_unlink();
            return 0;
        }
        n_cells = i + 1;
    }
    return 1;
#endif
}

/* Открытие существующих именованных семафоров (независимый садовник). */
int prims_attach(const char *base)
{
#if UNNAMED
    (void)base;
    return 0;
#else
    snprintf(base_name, sizeof base_name, "%s", base);
    creator_pid = 0;
    mtx_s = open_existing("m", -1);
    start_s = open_existing("s", -1);
    ready_s = open_existing("r", -1);
    done_s = open_existing("d", -1);
    if (!mtx_s || !start_s || !ready_s || !done_s) {
        err_msg("Не удалось открыть именованные семафоры '%s_*': %s", base_name, strerror(errno));
        return 0;
    }
    for (int i = 0; i < CELLSEMS; i++) {
        cell_s[i] = open_existing("c", i);
        if (!cell_s[i]) {
            err_msg("Не удалось открыть семафор клетки %d: %s", i, strerror(errno));
            return 0;
        }
        n_cells = i + 1;
    }
    return 1;
#endif
}

/* Закрытие дескрипторов именованных семафоров в текущем процессе. */
void prims_close(void)
{
#if !UNNAMED
    for (int i = 0; i < n_cells; i++)
        if (cell_s[i]) sem_close(cell_s[i]);
    if (mtx_s) sem_close(mtx_s);
    if (start_s) sem_close(start_s);
    if (ready_s) sem_close(ready_s);
    if (done_s) sem_close(done_s);
#endif
    n_cells = 0;
    mtx_s = start_s = ready_s = done_s = NULL;
}

/* Удаление семафоров: sem_unlink (именованные) или sem_destroy (неименованные).
 * Вызывается создателем и безопасна при повторном вызове. */
void prims_unlink(void)
{
    if (creator_pid != getpid()) return;
#if UNNAMED
    for (int i = 0; i < n_cells; i++) sem_destroy(&S->u_cell[i]);
    sem_destroy(&S->u_mtx);
    sem_destroy(&S->u_start);
    sem_destroy(&S->u_ready);
    sem_destroy(&S->u_done);
#else
    char nm[128];
    int total = n_cells > CELLSEMS ? n_cells : CELLSEMS;
    for (int i = 0; i < total; i++) {
        sem_name(nm, sizeof nm, "c", i);
        sem_unlink(nm);
    }
    sem_name(nm, sizeof nm, "m", -1); sem_unlink(nm);
    sem_name(nm, sizeof nm, "s", -1); sem_unlink(nm);
    sem_name(nm, sizeof nm, "r", -1); sem_unlink(nm);
    sem_name(nm, sizeof nm, "d", -1); sem_unlink(nm);
#endif
    creator_pid = 0;
}

/* Мьютекс на двоичном семафоре. */
void lock(void)
{
    while (sem_wait(mtx_s) < 0 && errno == EINTR) {}
}
void unlock(void) { sem_post(mtx_s); }

/* Захват мьютекса после гибели процесса: если держатель умер, семафор
 * никогда не освободится — через 1 с принудительно «возвращаем» его. */
void lock_recover(void)
{
    for (;;) {
        struct timespec ts;
        abs_deadline(&ts, 1000);
        int rc;
        while ((rc = sem_timedwait(mtx_s, &ts)) < 0 && errno == EINTR) {}
        if (rc == 0) return;
        sem_post(mtx_s);
    }
}

#ifdef IPC_MQ
/* В версии с очередью сообщений клетками распоряжается сервер (simulation_mq.c);
 * эти функции нужны только для сборки общего модуля gardener.c. */
int cell_try(int g, int c) { (void)g; (void)c; return 0; }
int cell_wait_slice(int g, int c, int ms) { (void)g; (void)c; (void)ms; return 0; }
void cell_release(int g, int c) { (void)g; (void)c; }
#else
/* Неблокирующий захват клетки. */
int cell_try(int g, int c)
{
    if (sem_trywait(cell_s[c]) != 0) return 0;
    lock();
    owner[c] = g;
    waiting_for[g] = -1;
    unlock();
    return 1;
}

/* Ожидание клетки не дольше ms мс. */
int cell_wait_slice(int g, int c, int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    int rc;
    while ((rc = sem_timedwait(cell_s[c], &ts)) < 0 && errno == EINTR) {}
    if (rc != 0) return 0;
    lock();
    owner[c] = g;
    waiting_for[g] = -1;
    unlock();
    return 1;
}

/* Освобождение клетки. owner сбрасывается ДО sem_post. */
void cell_release(int g, int c)
{
    (void)g;
    lock();
    owner[c] = -1;
    check_invariants_locked("освобождение клетки", 0);
    unlock();
    sem_post(cell_s[c]);
}

#endif

/* «Ворота» старта: открывающий добавляет NG разрешений. */
void start_open(void) { for (int i = 0; i < NG; i++) sem_post(start_s); }

/* Ожидание общего старта; 0 — получен запрос остановки. */
int start_wait(void)
{
    for (;;) {
        struct timespec ts;
        abs_deadline(&ts, 100);
        if (sem_timedwait(start_s, &ts) == 0) return 1;
        if (sig_stop || atomic_load(&halt_reason)) return 0;
    }
}

void ready_signal(void) { sem_post(ready_s); }
int ready_wait_slice(int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    return sem_timedwait(ready_s, &ts) == 0;
}

/* Неблокирующая проверка семафоров готовности и завершения (сервер сообщений). */
int ready_try(void) { return sem_trywait(ready_s) == 0; }
int done_try(void) { return sem_trywait(done_s) == 0; }

void done_signal(void) { sem_post(done_s); }
int done_wait_slice(int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    return sem_timedwait(done_s, &ts) == 0;
}

/* Аварийная очистка из обработчика сигнала (повторный Ctrl+C): только
 * системные вызовы удаления имён; вызывается лишь создателем объектов. */
void cleanup_ipc_on_signal(void)
{
    if (creator_pid == getpid()) {
#if !UNNAMED
        char nm[128];
        int total = n_cells > CELLSEMS ? n_cells : CELLSEMS;
        for (int i = 0; i < total; i++) {
            sem_name(nm, sizeof nm, "c", i);
            sem_unlink(nm);
        }
        sem_name(nm, sizeof nm, "m", -1); sem_unlink(nm);
        sem_name(nm, sizeof nm, "s", -1); sem_unlink(nm);
        sem_name(nm, sizeof nm, "r", -1); sem_unlink(nm);
        sem_name(nm, sizeof nm, "d", -1); sem_unlink(nm);
#endif
    }
    if (ipc_extra_cleanup) ipc_extra_cleanup();
    shared_unlink();
}
