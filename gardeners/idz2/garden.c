/*
 * garden.c — «Задача о нелюдимых садовниках» (вариант 15).
 *
 * Сад — прямоугольное поле клеток. Часть клеток недоступна (камни '#',
 * пруды '~'). Два садовника-потока обходят сад по своим маршрутам
 * (змейка по строкам или столбцам из заданного угла) и обрабатывают клетки.
 * Садовники не должны находиться в одной клетке одновременно.
 *
 * Модель потоков:
 *   - каждый садовник — отдельный pthread;
 *   - главный поток — «наблюдатель»: ждёт завершения садовников,
 *     обрабатывает сигналы (SIGUSR1 — показать карту), печатает итоги.
 *
 * Синхронизация (две сборки из одного исходника):
 *   - по умолчанию:  мьютекс (общее состояние и вывод) +
 *                    по одному бинарному семафору sem_t на клетку
 *                    (владение клеткой), семафоры «старт» и «конец»;
 *   - -DUSE_CV:      мьютекс + условная переменная (освобождение клетки),
 *                    барьер (одновременный старт), условная переменная
 *                    «конец работы». Семафоры не используются.
 *
 * Ввод-вывод: write()/read()/open() (дескрипторы файлов), лог в файл.
 * Завершение: нормальное, по сигналу (SIGINT/SIGTERM), по тупику.
 *
 * Сборка:  make            (garden_sem и garden_cv)
 * Запуск:  ./garden_sem -h
 */



#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define MAX_W 60
#define MAX_H 40
#define MAX_CELLS (MAX_W * MAX_H)
#define NG 2 /* число садовников */

/* Состояния клетки. Меняются только под мьютексом mtx. */
enum { CS_TODO = 0, CS_WORK, CS_DONE, CS_OBST };
/* Причины аварийной остановки модели. */
enum { HALT_NONE = 0, HALT_DEADLOCK, HALT_LIVELOCK };

#ifdef USE_CV
#define IMPL_NAME "мьютекс + условные переменные + барьер"
#else
#define IMPL_NAME "мьютекс + семафоры (sem_t)"
#endif

/* ------------------------------------------------------------------ */
/* Параметры модели                                                    */
/* ------------------------------------------------------------------ */
typedef struct {
    int w, h;                 /* размеры сада                             */
    int obst_pct;             /* доля недоступных клеток, %               */
    unsigned seed;            /* зерно генератора (0 — по времени)        */
    const char *map_file;     /* файл с картой (NULL — случайная)         */
    int start_set[NG];        /* стартовая клетка задана явно?            */
    int start_r[NG], start_c[NG]; /* стартовая клетка (с 1)               */
    int corner[NG];           /* угол маршрута: 0 TL, 1 TR, 2 BL, 3 BR    */
    int cols[NG];             /* 0 — змейка по строкам, 1 — по столбцам   */
    int move_ms[NG];          /* время перехода в соседнюю клетку, мс     */
    int work_ms[NG];          /* время обработки клетки, мс               */
    int bypass;               /* разрешён ли обход занятой клетки         */
    int view;                 /* 0 — события; 1 — +карта после обработки;
                                 2 — +карта после каждого перехода        */
    const char *log_path;     /* файл лога                                */
} Config;

static Config cfg;

/* ------------------------------------------------------------------ */
/* Состояние сада (защищено мьютексом mtx)                             */
/* ------------------------------------------------------------------ */
static int W, H, NC, NFREE;          /* ширина, высота, клеток, свободных */
static char obst[MAX_CELLS];         /* глиф препятствия или 0 (const)    */
static int cell_state[MAX_CELLS];    /* CS_*                              */
static int owner[MAX_CELLS];         /* кто занимает клетку (-1 никто)    */
static int waiting_for[NG];          /* клетка, которую ждёт садовник     */
static int route[NG][MAX_CELLS];     /* маршруты обхода (const)           */
static int start_cell[NG];

typedef struct {
    int id;
    pthread_t th;
    int pos;                  /* текущая клетка (-1 после завершения)     */
    int idx;                  /* позиция в маршруте                       */
    int move_ms, work_ms;
    int since_progress;       /* переходов с последней обработки клетки   */
    /* статистика */
    int processed, moves, waits, bypasses;
    int skipped_obst, skipped_done, unreachable;
    long wait_ms;
    const char *end_text;
} Gardener;

static Gardener gd[NG];

static pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;

/* Флаги остановки. */
static volatile sig_atomic_t sig_stop = 0; /* номер сигнала завершения   */
static volatile sig_atomic_t print_req = 0; /* запрос карты (SIGUSR1)    */
static atomic_int halt_reason;              /* HALT_*                    */

static int log_fd = -1;
static struct timespec t_start;

/* ------------------------------------------------------------------ */
/* Ввод-вывод через дескрипторы                                        */
/* ------------------------------------------------------------------ */
static void write_all(int fd, const char *b, size_t n)
{
    while (n > 0) {
        ssize_t k = write(fd, b, n);
        if (k < 0) {
            if (errno == EINTR) continue;
            return;
        }
        b += k;
        n -= (size_t)k;
    }
}

/* Вывод одновременно на экран (fd 1) и в лог. */
static void out_raw(const char *b, size_t n)
{
    write_all(1, b, n);
    if (log_fd >= 0) write_all(log_fd, b, n);
}

static void err_msg(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void err_msg(const char *fmt, ...)
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

static double elapsed(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)(t.tv_sec - t_start.tv_sec) +
           (double)(t.tv_nsec - t_start.tv_nsec) / 1e9;
}

/* Строка без метки времени (итоги, баннер). Только из одного потока. */
static void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void say(const char *fmt, ...)
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

/* Событие с меткой времени. Вызывать при захваченном mtx — тогда строки
 * разных потоков не перемешиваются и порядок событий согласован с состоянием. */
static void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void emit(const char *fmt, ...)
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

static void emit_g(int id, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
static void emit_g(int id, const char *fmt, ...)
{
    char body[500];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(body, sizeof body, fmt, ap);
    va_end(ap);
    emit("Садовник %d: %s", id + 1, body);
}

#define ROW(c) ((c) / W + 1) /* номер строки для вывода (с 1)  */
#define COL(c) ((c) % W + 1) /* номер столбца для вывода (с 1) */

/* Печать карты сада. mtx должен быть захвачен (или потоков уже нет).
 * '#','~' — недоступно, '.' — не обработано, '+' — обработано,
 * '1','2' — садовники. */
static void show_map(const char *title)
{
    char buf[MAX_H * (MAX_W * 2 + 8) + 256];
    int n = 0, done = 0;
    for (int c = 0; c < NC; c++)
        if (!obst[c] && cell_state[c] == CS_DONE) done++;
    n += snprintf(buf + n, sizeof buf - (size_t)n,
                  "    -- %s (обработано %d из %d) --\n", title, done, NFREE);
    for (int r = 0; r < H; r++) {
        n += snprintf(buf + n, sizeof buf - (size_t)n, "    ");
        for (int c = 0; c < W; c++) {
            int i = r * W + c;
            char ch;
            if (gd[0].pos == i) ch = '1';
            else if (gd[1].pos == i) ch = '2';
            else if (obst[i]) ch = obst[i];
            else if (cell_state[i] == CS_DONE) ch = '+';
            else ch = '.';
            buf[n++] = ch;
            buf[n++] = ' ';
        }
        buf[n++] = '\n';
    }
    out_raw(buf, (size_t)n);
}

/* ------------------------------------------------------------------ */
/* Паузы                                                               */
/* ------------------------------------------------------------------ */
static int aborted(void) { return sig_stop || atomic_load(&halt_reason); }

/* Пауза с проверкой остановки каждые ≤20 мс.
 * Возвращает 1, если пауза отработана полностью. */
static int sleep_ms(int ms)
{
    while (ms > 0) {
        if (aborted()) return 0;
        int s = ms > 20 ? 20 : ms;
        struct timespec ts = {0, (long)s * 1000000L};
        nanosleep(&ts, NULL);
        ms -= s;
    }
    return 1;
}

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

/* ------------------------------------------------------------------ */
/* Примитивы синхронизации (две реализации)                            */
/* ------------------------------------------------------------------ */
#ifndef USE_CV
static sem_t csem[MAX_CELLS]; /* владение клеткой: 1 — свободна          */
static sem_t start_sem;       /* «ворота» старта                          */
static sem_t done_sem;        /* садовник завершил работу                 */

static void prims_init(void)
{
    for (int i = 0; i < NC; i++) sem_init(&csem[i], 0, 1);
    sem_init(&start_sem, 0, 0);
    sem_init(&done_sem, 0, 0);
}
static void prims_destroy(void)
{
    for (int i = 0; i < NC; i++) sem_destroy(&csem[i]);
    sem_destroy(&start_sem);
    sem_destroy(&done_sem);
}
/* Неблокирующий захват клетки. */
static int cell_try(int g, int c)
{
    if (sem_trywait(&csem[c]) != 0) return 0;
    pthread_mutex_lock(&mtx);
    owner[c] = g;
    waiting_for[g] = -1;
    pthread_mutex_unlock(&mtx);
    return 1;
}
/* Ожидание клетки не дольше ms мс. */
static int cell_wait_slice(int g, int c, int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    int rc;
    while ((rc = sem_timedwait(&csem[c], &ts)) < 0 && errno == EINTR) {}
    if (rc != 0) return 0;
    pthread_mutex_lock(&mtx);
    owner[c] = g;
    waiting_for[g] = -1;
    pthread_mutex_unlock(&mtx);
    return 1;
}
/* Освобождение клетки. owner сбрасывается ДО sem_post. */
static void cell_release(int g, int c)
{
    (void)g;
    pthread_mutex_lock(&mtx);
    owner[c] = -1;
    pthread_mutex_unlock(&mtx);
    sem_post(&csem[c]);
}
static void start_open(void) { for (int i = 0; i < NG; i++) sem_post(&start_sem); }
static void start_wait(void) { while (sem_wait(&start_sem) < 0 && errno == EINTR) {} }
static void done_signal(void) { sem_post(&done_sem); }
static int done_wait_slice(int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    return sem_timedwait(&done_sem, &ts) == 0;
}
#else /* USE_CV */
static pthread_cond_t cell_cv = PTHREAD_COND_INITIALIZER; /* клетка освободилась */
static pthread_cond_t done_cv = PTHREAD_COND_INITIALIZER; /* садовник закончил   */
static pthread_barrier_t start_barrier;                   /* общий старт         */
static int done_count = 0;                                /* под mtx             */

static void prims_init(void) { pthread_barrier_init(&start_barrier, NULL, NG + 1); }
static void prims_destroy(void) { pthread_barrier_destroy(&start_barrier); }
static int cell_try(int g, int c)
{
    int ok = 0;
    pthread_mutex_lock(&mtx);
    if (owner[c] < 0) {
        owner[c] = g;
        waiting_for[g] = -1;
        ok = 1;
    }
    pthread_mutex_unlock(&mtx);
    return ok;
}
static int cell_wait_slice(int g, int c, int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    int ok = 0;
    pthread_mutex_lock(&mtx);
    while (owner[c] >= 0) {
        if (pthread_cond_timedwait(&cell_cv, &mtx, &ts) == ETIMEDOUT) break;
    }
    if (owner[c] < 0) {
        owner[c] = g;
        waiting_for[g] = -1;
        ok = 1;
    }
    pthread_mutex_unlock(&mtx);
    return ok;
}
static void cell_release(int g, int c)
{
    (void)g;
    pthread_mutex_lock(&mtx);
    owner[c] = -1;
    pthread_cond_broadcast(&cell_cv);
    pthread_mutex_unlock(&mtx);
}
static void start_open(void) { pthread_barrier_wait(&start_barrier); }
static void start_wait(void) { pthread_barrier_wait(&start_barrier); }
static void done_signal(void)
{
    pthread_mutex_lock(&mtx);
    done_count++;
    pthread_cond_signal(&done_cv);
    pthread_mutex_unlock(&mtx);
}
static int done_wait_slice(int ms)
{
    struct timespec ts;
    abs_deadline(&ts, ms);
    int r = 0;
    pthread_mutex_lock(&mtx);
    if (done_count == 0) pthread_cond_timedwait(&done_cv, &mtx, &ts);
    if (done_count > 0) {
        done_count--;
        r = 1;
    }
    pthread_mutex_unlock(&mtx);
    return r;
}
#endif

/* ------------------------------------------------------------------ */
/* Маршруты и поиск пути                                               */
/* ------------------------------------------------------------------ */
static const char *corner_name[4] = {"левый верхний", "правый верхний",
                                     "левый нижний", "правый нижний"};

/* Маршрут-змейка из угла corner: по строкам (cols=0) или столбцам (cols=1). */
static void gen_route(int g, int corner, int cols)
{
    int right = corner & 1, bottom = corner >> 1, n = 0;
    int outer = cols ? W : H, inner = cols ? H : W;
    for (int i = 0; i < outer; i++) {
        for (int k = 0; k < inner; k++) {
            int kk = (i % 2 == 0) ? k : inner - 1 - k; /* змейка */
            int r, c;
            if (!cols) {
                r = bottom ? H - 1 - i : i;
                c = right ? W - 1 - kk : kk;
            } else {
                c = right ? W - 1 - i : i;
                r = bottom ? H - 1 - kk : kk;
            }
            route[g][n++] = r * W + c;
        }
    }
}

static const int DR[4] = {-1, 1, 0, 0};
static const int DC[4] = {0, 0, -1, 1};

/* Первый шаг кратчайшего пути from -> to по доступным клеткам.
 * avoid_owner >= 0: клетки, занятые этим садовником, считаются стеной
 * (тогда mtx должен быть захвачен). Возвращает -1, если пути нет. */
static int bfs_next(int from, int to, int avoid_owner)
{
    int dist[MAX_CELLS], q[MAX_CELLS], head = 0, tail = 0;
    if (from == to) return -1;
    for (int i = 0; i < NC; i++) dist[i] = -1;
    if (avoid_owner >= 0 && owner[to] == avoid_owner) return -1;
    dist[to] = 0;
    q[tail++] = to;
    while (head < tail) {
        int c = q[head++];
        if (c == from) break;
        for (int d = 0; d < 4; d++) {
            int nr = c / W + DR[d], nc = c % W + DC[d];
            if (nr < 0 || nr >= H || nc < 0 || nc >= W) continue;
            int n = nr * W + nc;
            if (dist[n] >= 0 || obst[n]) continue;
            if (avoid_owner >= 0 && owner[n] == avoid_owner) continue;
            dist[n] = dist[c] + 1;
            q[tail++] = n;
        }
    }
    if (dist[from] < 0) return -1;
    for (int d = 0; d < 4; d++) {
        int nr = from / W + DR[d], nc = from % W + DC[d];
        if (nr < 0 || nr >= H || nc < 0 || nc >= W) continue;
        int n = nr * W + nc;
        if (!obst[n] && dist[n] == dist[from] - 1 &&
            (avoid_owner < 0 || owner[n] != avoid_owner))
            return n;
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/* Поведение садовника                                                 */
/* ------------------------------------------------------------------ */

/* Взаимное ожидание двух садовников (mtx захвачен). */
static int check_deadlock_locked(int me)
{
    int ot = 1 - me, wm = waiting_for[me], wo = waiting_for[ot];
    if (wm < 0 || wo < 0) return 0;
    return owner[wm] == ot && owner[wo] == me;
}

/* Ожидание занятой клетки c. 1 — клетка захвачена, 0 — остановка. */
static int wait_enter(Gardener *g, int c)
{
    int me = g->id;
    double t0 = elapsed();
    pthread_mutex_lock(&mtx);
    waiting_for[me] = c;
    g->waits++;
    emit_g(me, "клетка (%d,%d) занята другим садовником — ожидает освобождения",
           ROW(c), COL(c));
    pthread_mutex_unlock(&mtx);
    for (;;) {
        if (cell_wait_slice(me, c, 20)) {
            pthread_mutex_lock(&mtx);
            long ms = (long)((elapsed() - t0) * 1000.0);
            g->wait_ms += ms;
            emit_g(me, "дождался освобождения клетки (%d,%d), ждал %ld мс",
                   ROW(c), COL(c), ms);
            pthread_mutex_unlock(&mtx);
            return 1;
        }
        pthread_mutex_lock(&mtx);
        if (aborted()) {
            waiting_for[me] = -1;
            pthread_mutex_unlock(&mtx);
            return 0;
        }
        if (check_deadlock_locked(me)) {
            int exp = HALT_NONE;
            if (atomic_compare_exchange_strong(&halt_reason, &exp, HALT_DEADLOCK))
                emit("ТУПИК: садовник %d ждёт клетку (%d,%d), занятую садовником %d, "
                     "а тот ждёт клетку (%d,%d), занятую первым",
                     me + 1, ROW(c), COL(c), 2 - me, ROW(waiting_for[1 - me]),
                     COL(waiting_for[1 - me]));
            waiting_for[me] = -1;
            pthread_mutex_unlock(&mtx);
            return 0;
        }
        pthread_mutex_unlock(&mtx);
    }
}

/* Переход в соседнюю клетку step (она уже захвачена садовником).
 * Во время перехода занята и старая, и новая клетка. */
static void do_move(Gardener *g, int step)
{
    int me = g->id, from = g->pos;
    pthread_mutex_lock(&mtx);
    g->moves++;
    g->since_progress++;
    emit_g(me, "переходит (%d,%d) -> (%d,%d)", ROW(from), COL(from), ROW(step),
           COL(step));
    pthread_mutex_unlock(&mtx);
    sleep_ms(g->move_ms);
    pthread_mutex_lock(&mtx);
    g->pos = step;
    if (cfg.view >= 2) show_map("после перехода");
    pthread_mutex_unlock(&mtx);
    cell_release(me, from);
}

/* Путь к клетке target. 1 — пришёл, 0 — клетка недостижима, -1 — остановка. */
static int walk_to(Gardener *g, int target)
{
    int me = g->id, other = 1 - me;
    while (g->pos != target) {
        if (aborted()) return -1;
        if (g->since_progress > 4 * NC + 16) {
            int exp = HALT_NONE;
            pthread_mutex_lock(&mtx);
            if (atomic_compare_exchange_strong(&halt_reason, &exp, HALT_LIVELOCK))
                emit_g(me, "много переходов без обработки клеток — зацикливание");
            pthread_mutex_unlock(&mtx);
            return -1;
        }
        int sstep = bfs_next(g->pos, target, -1); /* путь без учёта соседа */
        if (sstep < 0) return 0;
        int step = sstep, sblocked = 0;
        if (cfg.bypass) { /* разрешён обход: ищем путь мимо занятых клеток */
            pthread_mutex_lock(&mtx);
            int alt = bfs_next(g->pos, target, other);
            sblocked = (owner[sstep] == other);
            pthread_mutex_unlock(&mtx);
            if (alt >= 0) step = alt;
        }
        if (cell_try(me, step)) {
            if (step != sstep && sblocked) {
                pthread_mutex_lock(&mtx);
                g->bypasses++;
                emit_g(me, "клетка (%d,%d) занята — обходит через (%d,%d)",
                       ROW(sstep), COL(sstep), ROW(step), COL(step));
                pthread_mutex_unlock(&mtx);
            }
            do_move(g, step);
            continue;
        }
        if (wait_enter(g, step) <= 0) return -1;
        do_move(g, step);
    }
    return 1;
}

/* Следующая необработанная клетка маршрута (с пропуском недоступных и
 * уже обработанных). -1 — маршрут исчерпан. */
static int next_target(Gardener *g)
{
    while (g->idx < NC) {
        int c = route[g->id][g->idx];
        pthread_mutex_lock(&mtx);
        if (obst[c]) {
            emit_g(g->id, "пропускает недоступную клетку (%d,%d) [%c]", ROW(c),
                   COL(c), obst[c]);
            g->skipped_obst++;
        } else if (cell_state[c] != CS_TODO) {
            emit_g(g->id, "пропускает клетку (%d,%d): %s", ROW(c), COL(c),
                   cell_state[c] == CS_DONE ? "уже обработана"
                                            : "её сейчас обрабатывает другой");
            g->skipped_done++;
        } else {
            pthread_mutex_unlock(&mtx);
            return c;
        }
        g->idx++;
        pthread_mutex_unlock(&mtx);
    }
    return -1;
}

/* Обработка клетки, в которой стоит садовник. Клетка обрабатывается
 * не более одного раза: состояние TODO -> WORK -> DONE под мьютексом. */
static void process_cell(Gardener *g)
{
    int c = g->pos, me = g->id;
    pthread_mutex_lock(&mtx);
    if (cell_state[c] != CS_TODO) {
        emit_g(me, "клетка (%d,%d) уже обработана — пропуск", ROW(c), COL(c));
        pthread_mutex_unlock(&mtx);
        return;
    }
    cell_state[c] = CS_WORK;
    emit_g(me, "начал обработку клетки (%d,%d), %d мс", ROW(c), COL(c), g->work_ms);
    pthread_mutex_unlock(&mtx);

    int full = sleep_ms(g->work_ms);

    pthread_mutex_lock(&mtx);
    if (!full) {
        cell_state[c] = CS_TODO; /* прервано — клетка остаётся необработанной */
        emit_g(me, "обработка клетки (%d,%d) прервана", ROW(c), COL(c));
    } else {
        cell_state[c] = CS_DONE;
        g->processed++;
        g->since_progress = 0;
        emit_g(me, "закончил обработку клетки (%d,%d)", ROW(c), COL(c));
        if (cfg.view >= 1) show_map("клетка обработана");
    }
    pthread_mutex_unlock(&mtx);
}

static void *gardener_main(void *arg)
{
    Gardener *g = arg;
    int me = g->id;
    int normal = 0;

    start_wait();
    pthread_mutex_lock(&mtx);
    emit_g(me, "приступил к работе, стартовая клетка (%d,%d)", ROW(g->pos),
           COL(g->pos));
    pthread_mutex_unlock(&mtx);

    while (!aborted()) {
        int t = next_target(g);
        if (t < 0) {
            normal = 1;
            break;
        }
        int r = walk_to(g, t);
        if (r < 0) break;
        if (r == 0) {
            pthread_mutex_lock(&mtx);
            emit_g(me, "клетка (%d,%d) недостижима — пропуск", ROW(t), COL(t));
            g->unreachable++;
            pthread_mutex_unlock(&mtx);
        } else {
            process_cell(g);
        }
        g->idx++;
    }

    if (normal) g->end_text = "маршрут пройден";
    else if (sig_stop) g->end_text = "прерван сигналом";
    else if (atomic_load(&halt_reason) == HALT_DEADLOCK) g->end_text = "прерван: тупик";
    else g->end_text = "прерван: зацикливание";

    /* Освобождаем ресурсы: клетку, в которой стоит садовник. */
    pthread_mutex_lock(&mtx);
    int last = g->pos;
    g->pos = -1;
    emit_g(me, "завершает работу (%s), освобождает клетку (%d,%d)", g->end_text,
           ROW(last), COL(last));
    if (cfg.view >= 1) show_map("садовник ушёл");
    pthread_mutex_unlock(&mtx);
    cell_release(me, last);
    done_signal();
    return NULL;
}

/* ------------------------------------------------------------------ */
/* Сигналы                                                             */
/* ------------------------------------------------------------------ */
static void on_signal(int s)
{
    if (s == SIGUSR1) {
        print_req = 1;
        return;
    }
    if (sig_stop && s == SIGINT) _exit(130); /* повторный Ctrl+C — аварийно */
    sig_stop = s;
}

/* ------------------------------------------------------------------ */
/* Построение мира                                                     */
/* ------------------------------------------------------------------ */
static int load_map(const char *path)
{
    static char buf[8192];
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        err_msg("Не могу открыть карту '%s': %s", path, strerror(errno));
        return 0;
    }
    size_t len = 0;
    for (;;) {
        ssize_t k = read(fd, buf + len, sizeof buf - 1 - len);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) break;
        len += (size_t)k;
        if (len >= sizeof buf - 1) break;
    }
    close(fd);
    buf[len] = 0;
    int rows = 0, width = -1;
    char *p = buf;
    while (*p) {
        char *e = strchr(p, '\n');
        size_t l = e ? (size_t)(e - p) : strlen(p);
        char *next = e ? e + 1 : p + l;
        if (l > 0 && p[l - 1] == '\r') l--;
        if (l == 0) { p = next; continue; } /* пустые строки пропускаем */
        if (width < 0) width = (int)l;
        if ((int)l != width || width > MAX_W || rows >= MAX_H) {
            err_msg("Карта '%s': строки разной длины или превышен размер %dx%d",
                    path, MAX_W, MAX_H);
            return 0;
        }
        for (int c = 0; c < width; c++)
            obst[rows * width + c] = (p[c] == '#' || p[c] == '~') ? p[c] : 0;
        rows++;
        p = next;
    }
    if (rows == 0 || width <= 0) {
        err_msg("Карта '%s' пуста", path);
        return 0;
    }
    W = width;
    H = rows;
    return 1;
}

static int build_world(void)
{
    memset(obst, 0, sizeof obst);
    if (cfg.map_file) {
        if (!load_map(cfg.map_file)) return 0;
    } else {
        W = cfg.w;
        H = cfg.h;
    }
    NC = W * H;
    for (int g = 0; g < NG; g++) {
        gen_route(g, cfg.corner[g], cfg.cols[g]);
        if (cfg.start_set[g]) {
            int r = cfg.start_r[g], c = cfg.start_c[g];
            if (r < 1 || r > H || c < 1 || c > W) {
                err_msg("Стартовая клетка садовника %d (%d,%d) вне сада %dx%d", g + 1,
                        r, c, H, W);
                return 0;
            }
            start_cell[g] = (r - 1) * W + (c - 1);
        } else {
            start_cell[g] = route[g][0];
        }
    }
    if (start_cell[0] == start_cell[1]) {
        err_msg("Стартовые клетки садовников совпадают — они не могут стоять вместе");
        return 0;
    }
    if (!cfg.map_file) { /* случайные препятствия, старты всегда свободны */
        unsigned seed = cfg.seed;
        for (int c = 0; c < NC; c++) {
            if (c == start_cell[0] || c == start_cell[1]) continue;
            if ((int)(rand_r(&seed) % 100) < cfg.obst_pct)
                obst[c] = (rand_r(&seed) % 100 < 60) ? '#' : '~';
        }
    }
    for (int g = 0; g < NG; g++) {
        if (obst[start_cell[g]]) {
            err_msg("Стартовая клетка садовника %d (%d,%d) недоступна", g + 1,
                    ROW(start_cell[g]), COL(start_cell[g]));
            return 0;
        }
    }
    NFREE = 0;
    for (int c = 0; c < NC; c++) {
        owner[c] = -1;
        cell_state[c] = obst[c] ? CS_OBST : CS_TODO;
        if (!obst[c]) NFREE++;
    }
    for (int g = 0; g < NG; g++) waiting_for[g] = -1;
    return 1;
}

/* Заливка достижимых клеток от start (для диагностики). */
static void flood(int start, char *seen)
{
    int q[MAX_CELLS], head = 0, tail = 0;
    seen[start] = 1;
    q[tail++] = start;
    while (head < tail) {
        int c = q[head++];
        for (int d = 0; d < 4; d++) {
            int nr = c / W + DR[d], nc = c % W + DC[d];
            if (nr < 0 || nr >= H || nc < 0 || nc >= W) continue;
            int n = nr * W + nc;
            if (seen[n] || obst[n]) continue;
            seen[n] = 1;
            q[tail++] = n;
        }
    }
}

/* Итоги и диагностика. Вызывается после join. Возвращает код выхода. */
static int print_summary(void)
{
    char reach[MAX_CELLS];
    memset(reach, 0, sizeof reach);
    flood(start_cell[0], reach);
    flood(start_cell[1], reach);
    int done = 0, unreach = 0, left = 0;
    for (int c = 0; c < NC; c++) {
        if (obst[c]) continue;
        if (cell_state[c] == CS_DONE) done++;
        else if (!reach[c]) unreach++;
        else left++;
    }
    int sig = sig_stop, halt = atomic_load(&halt_reason);
    int code = 0;
    say("%s", "");
    say("==================== ИТОГ ====================");
    if (sig) {
        say("Причина завершения: прервано сигналом %d (%s)", sig, strsignal(sig));
        code = 3;
    } else if (halt == HALT_DEADLOCK) {
        say("Причина завершения: тупик — садовники взаимно ждут друг друга, обход невозможен");
        code = 2;
    } else if (halt == HALT_LIVELOCK) {
        say("Причина завершения: зацикливание — обход невозможно продолжить");
        code = 2;
    } else if (left > 0) {
        say("Причина завершения: обход остановлен, остались необработанные клетки");
        code = 2;
    } else {
        say("Причина завершения: все достижимые клетки обработаны");
    }
    say("Время моделирования: %.3f с", elapsed());
    say("Обработано клеток: %d из %d доступных; препятствий: %d", done, NFREE, NC - NFREE);
    for (int g = 0; g < NG; g++) {
        Gardener *p = &gd[g];
        say("Садовник %d: обработано=%d, переходов=%d, ожиданий=%d (%ld мс), обходов=%d, "
            "пропущено препятствий=%d, пропущено обработанных=%d, недостижимых=%d; %s",
            g + 1, p->processed, p->moves, p->waits, p->wait_ms, p->bypasses,
            p->skipped_obst, p->skipped_done, p->unreachable,
            p->end_text ? p->end_text : "-");
    }
    if (unreach + left > 0) {
        say("Диагностика необработанных участков (%d клеток):", unreach + left);
        int shown = 0;
        for (int c = 0; c < NC; c++) {
            if (obst[c] || cell_state[c] == CS_DONE) continue;
            if (shown++ < 40)
                say("  (%d,%d) — %s", ROW(c), COL(c),
                    reach[c] ? "достижима, но не обработана (остановка обхода)"
                             : "недостижима: изолирована препятствиями");
        }
        if (shown > 40) say("  ... и ещё %d", shown - 40);
    }
    show_map("итоговое состояние сада");
    return code;
}

/* ------------------------------------------------------------------ */
/* Интерфейс: командная строка и диалог                                */
/* ------------------------------------------------------------------ */
static void usage(const char *prog)
{
    char b[2600];
    int n = snprintf(b, sizeof b,
        "Нелюдимые садовники (вариант 15). Сборка: " IMPL_NAME "\n"
        "Использование: %s [параметры]   (без параметров в терминале — диалог)\n"
        "  -W N       ширина сада, клеток (по умолчанию 10, максимум %d)\n"
        "  -H N       высота сада (по умолчанию 6, максимум %d)\n"
        "  -p P       доля недоступных клеток, %% (по умолчанию 15)\n"
        "  -r SEED    зерно генератора препятствий (по умолчанию — от времени)\n"
        "  -m FILE    карта из файла ('#' камень, '~' пруд, остальное — свободно)\n"
        "  -a R,C     стартовая клетка садовника 1 (с 1); по умолчанию угол маршрута\n"
        "  -b R,C     стартовая клетка садовника 2\n"
        "  -A СПЕЦ    маршрут садовника 1: УГОЛ[:rows|cols], УГОЛ = TL,TR,BL,BR\n"
        "             (по умолчанию TL:rows — змейка по строкам из левого верхнего)\n"
        "  -B СПЕЦ    маршрут садовника 2 (по умолчанию BR:rows)\n"
        "  -t A,B     время перехода между клетками, мс (по умолчанию 150,150)\n"
        "  -k A,B     время обработки клетки, мс (по умолчанию 300,300)\n"
        "  -o         разрешить обход занятой клетки (по умолчанию — только ждать)\n"
        "  -v N       0 события; 1 +карта после обработки (умолч.); 2 +после переходов\n"
        "  -l FILE    файл лога (по умолчанию garden.log)\n"
        "  -i         принудительный диалог ввода параметров\n"
        "  -h         эта справка\n"
        "Сигналы: SIGINT/SIGTERM — корректная остановка; SIGUSR1 — показать карту.\n"
        "Коды выхода: 0 всё обработано; 1 ошибка параметров; 2 тупик/необработанные;\n"
        "             3 прервано сигналом.\n",
        prog, MAX_W, MAX_H);
    write_all(1, b, (size_t)n);
}

static int read_line(char *buf, size_t n)
{
    size_t i = 0;
    char ch;
    for (;;) {
        ssize_t k = read(0, &ch, 1);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) {
            if (i == 0) { buf[0] = 0; return -1; }
            break;
        }
        if (ch == '\n') break;
        if (i + 1 < n) buf[i++] = ch;
    }
    buf[i] = 0;
    return (int)i;
}

static int ask_int(const char *q, int def, int lo, int hi)
{
    char line[64], msg[256];
    for (;;) {
        int n = snprintf(msg, sizeof msg, "%s [%d]: ", q, def);
        write_all(1, msg, (size_t)n);
        if (read_line(line, sizeof line) < 0 || !line[0]) return def;
        char *e;
        long v = strtol(line, &e, 10);
        if (*e || v < lo || v > hi) {
            n = snprintf(msg, sizeof msg, "  ожидается число от %d до %d\n", lo, hi);
            write_all(1, msg, (size_t)n);
            continue;
        }
        return (int)v;
    }
}

static void ask_str(const char *q, const char *def, char *out, size_t n)
{
    char msg[256];
    int k = snprintf(msg, sizeof msg, "%s [%s]: ", q, def);
    write_all(1, msg, (size_t)k);
    if (read_line(out, n) < 0 || !out[0]) snprintf(out, n, "%s", def);
}

static int parse_route(const char *s, int *corner, int *cols)
{
    char a[8] = {0}, b[8] = {0};
    int k = sscanf(s, " %7[A-Za-z] : %7[A-Za-z]", a, b);
    if (k < 1) return 0;
    for (char *p = a; *p; p++) if (*p >= 'a' && *p <= 'z') *p -= 32;
    for (char *p = b; *p; p++) if (*p >= 'A' && *p <= 'Z') *p += 32;
    if (!strcmp(a, "TL")) *corner = 0;
    else if (!strcmp(a, "TR")) *corner = 1;
    else if (!strcmp(a, "BL")) *corner = 2;
    else if (!strcmp(a, "BR")) *corner = 3;
    else return 0;
    if (k == 1 || !strcmp(b, "rows") || !strcmp(b, "r")) *cols = 0;
    else if (!strcmp(b, "cols") || !strcmp(b, "c")) *cols = 1;
    else return 0;
    return 1;
}

static int parse_pair(const char *s, int *a, int *b)
{
    int k = sscanf(s, " %d , %d", a, b);
    if (k == 1) { *b = *a; k = 2; }
    return k == 2 && *a >= 0 && *b >= 0;
}

static int parse_rc(const char *s, int *r, int *c)
{
    return sscanf(s, " %d , %d", r, c) == 2;
}

static void interactive(void)
{
    char s[128];
    say("=== Диалог настройки (Enter — значение по умолчанию) ===");
    ask_str("Файл карты (пусто/- — случайный сад)", "-", s, sizeof s);
    static char mapname[128];
    if (strcmp(s, "-") != 0) {
        snprintf(mapname, sizeof mapname, "%s", s);
        cfg.map_file = mapname;
    } else {
        cfg.w = ask_int("Ширина сада", cfg.w, 1, MAX_W);
        cfg.h = ask_int("Высота сада", cfg.h, 1, MAX_H);
        cfg.obst_pct = ask_int("Доля недоступных клеток, %", cfg.obst_pct, 0, 90);
        cfg.seed = (unsigned)ask_int("Зерно генератора (0 — от времени)", 0, 0, 1000000000);
    }
    for (int g = 0; g < NG; g++) {
        char q[160], def[16];
        static char dummy[2];
        (void)dummy;
        snprintf(q, sizeof q, "Маршрут садовника %d (УГОЛ:rows|cols, угол TL/TR/BL/BR)", g + 1);
        snprintf(def, sizeof def, "%s:%s", g == 0 ? "TL" : "BR", "rows");
        for (;;) {
            ask_str(q, def, s, sizeof s);
            if (parse_route(s, &cfg.corner[g], &cfg.cols[g])) break;
            say("  неверная спецификация маршрута");
        }
        snprintf(q, sizeof q, "Стартовая клетка садовника %d (строка,столбец; - угол маршрута)", g + 1);
        ask_str(q, "-", s, sizeof s);
        if (parse_rc(s, &cfg.start_r[g], &cfg.start_c[g])) cfg.start_set[g] = 1;
        snprintf(q, sizeof q, "Время перехода садовника %d, мс", g + 1);
        cfg.move_ms[g] = ask_int(q, cfg.move_ms[g], 0, 10000);
        snprintf(q, sizeof q, "Время обработки клетки садовником %d, мс", g + 1);
        cfg.work_ms[g] = ask_int(q, cfg.work_ms[g], 0, 10000);
    }
    cfg.bypass = ask_int("Разрешить обход занятой клетки (0 нет, 1 да)", cfg.bypass, 0, 1);
    cfg.view = ask_int("Режим карты (0 события, 1 после обработки, 2 после переходов)",
                       cfg.view, 0, 2);
}

static int to_int(const char *s, int lo, int hi, const char *what)
{
    char *e;
    long v = strtol(s, &e, 10);
    if (*s == 0 || *e || v < lo || v > hi) {
        err_msg("Параметр %s: ожидается число от %d до %d, получено '%s'", what, lo, hi, s);
        exit(1);
    }
    return (int)v;
}

int main(int argc, char **argv)
{
    cfg = (Config){.w = 10, .h = 6, .obst_pct = 15, .seed = 0,
                   .corner = {0, 3}, .cols = {0, 0},
                   .move_ms = {150, 150}, .work_ms = {300, 300},
                   .bypass = 0, .view = 1, .log_path = "garden.log"};
    int force_dialog = 0;
    int opt;
    while ((opt = getopt(argc, argv, "W:H:p:r:m:a:b:A:B:t:k:ov:l:ih")) != -1) {
        switch (opt) {
        case 'W': cfg.w = to_int(optarg, 1, MAX_W, "-W"); break;
        case 'H': cfg.h = to_int(optarg, 1, MAX_H, "-H"); break;
        case 'p': cfg.obst_pct = to_int(optarg, 0, 90, "-p"); break;
        case 'r': cfg.seed = (unsigned)to_int(optarg, 0, 2000000000, "-r"); break;
        case 'm': cfg.map_file = optarg; break;
        case 'a':
            if (!parse_rc(optarg, &cfg.start_r[0], &cfg.start_c[0])) { err_msg("-a ожидает R,C"); return 1; }
            cfg.start_set[0] = 1;
            break;
        case 'b':
            if (!parse_rc(optarg, &cfg.start_r[1], &cfg.start_c[1])) { err_msg("-b ожидает R,C"); return 1; }
            cfg.start_set[1] = 1;
            break;
        case 'A':
            if (!parse_route(optarg, &cfg.corner[0], &cfg.cols[0])) { err_msg("-A: неверный маршрут '%s'", optarg); return 1; }
            break;
        case 'B':
            if (!parse_route(optarg, &cfg.corner[1], &cfg.cols[1])) { err_msg("-B: неверный маршрут '%s'", optarg); return 1; }
            break;
        case 't':
            if (!parse_pair(optarg, &cfg.move_ms[0], &cfg.move_ms[1])) { err_msg("-t ожидает A,B (мс)"); return 1; }
            break;
        case 'k':
            if (!parse_pair(optarg, &cfg.work_ms[0], &cfg.work_ms[1])) { err_msg("-k ожидает A,B (мс)"); return 1; }
            break;
        case 'o': cfg.bypass = 1; break;
        case 'v': cfg.view = to_int(optarg, 0, 2, "-v"); break;
        case 'l': cfg.log_path = optarg; break;
        case 'i': force_dialog = 1; break;
        case 'h': usage(argv[0]); return 0;
        default: usage(argv[0]); return 1;
        }
    }
    if (force_dialog || (argc == 1 && isatty(0))) interactive();
    if (cfg.seed == 0) cfg.seed = (unsigned)time(NULL);

    clock_gettime(CLOCK_MONOTONIC, &t_start);
    if (!build_world()) return 1;

    log_fd = open(cfg.log_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (log_fd < 0)
        err_msg("Предупреждение: лог '%s' не открыт: %s", cfg.log_path, strerror(errno));

    /* Обработчики сигналов (без SA_RESTART, чтобы прерывать ожидания). */
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGUSR1, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    say("==== Нелюдимые садовники. Сборка: %s ====", IMPL_NAME);
    say("Сад %d x %d (строк x столбцов), доступных клеток %d, препятствий %d%s%s",
        H, W, NFREE, NC - NFREE, cfg.map_file ? ", карта: " : ", зерно: ",
        cfg.map_file ? cfg.map_file : "");
    if (!cfg.map_file) say("Доля препятствий %d%%, зерно %u", cfg.obst_pct, cfg.seed);
    for (int g = 0; g < NG; g++)
        say("Садовник %d: старт (%d,%d), маршрут: %s угол, змейка по %s; "
            "переход %d мс, обработка %d мс",
            g + 1, ROW(start_cell[g]), COL(start_cell[g]), corner_name[cfg.corner[g]],
            cfg.cols[g] ? "столбцам" : "строкам", cfg.move_ms[g], cfg.work_ms[g]);
    say("Обход занятой клетки: %s; режим карты: %d; лог: %s",
        cfg.bypass ? "разрешён" : "запрещён (только ожидание)", cfg.view,
        log_fd >= 0 ? cfg.log_path : "-");
    say("Легенда: # камень, ~ пруд, . не обработано, + обработано, 1/2 садовники");
    show_map("начальное состояние сада");

    prims_init();
    for (int g = 0; g < NG; g++) {
        gd[g].id = g;
        gd[g].pos = start_cell[g];
        gd[g].move_ms = cfg.move_ms[g];
        gd[g].work_ms = cfg.work_ms[g];
        cell_try(g, start_cell[g]); /* стартовая клетка занята садовником */
    }

    /* Потоки садовников наследуют маску: блокируем сигналы, чтобы их
     * принимал только главный поток. */
    sigset_t set, old;
    sigemptyset(&set);
    sigaddset(&set, SIGINT);
    sigaddset(&set, SIGTERM);
    sigaddset(&set, SIGUSR1);
    pthread_sigmask(SIG_BLOCK, &set, &old);
    for (int g = 0; g < NG; g++) {
        if (pthread_create(&gd[g].th, NULL, gardener_main, &gd[g]) != 0) {
            err_msg("Не удалось создать поток садовника %d", g + 1);
            return 1;
        }
    }
    pthread_sigmask(SIG_SETMASK, &old, NULL);

    start_open(); /* одновременный старт */

    /* Главный поток: ждёт завершения обоих садовников, показывает карту по SIGUSR1. */
    int remaining = NG;
    while (remaining > 0) {
        remaining -= done_wait_slice(100);
        if (print_req) {
            print_req = 0;
            pthread_mutex_lock(&mtx);
            show_map("состояние по запросу (SIGUSR1)");
            pthread_mutex_unlock(&mtx);
        }
    }
    for (int g = 0; g < NG; g++) pthread_join(gd[g].th, NULL);

    int code = print_summary();
    prims_destroy();
    if (log_fd >= 0) close(log_fd);
    return code;
}
