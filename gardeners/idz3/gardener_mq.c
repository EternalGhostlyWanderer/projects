/* Независимый процесс-садовник для версии с очередями сообщений
 * (gardener_mq1 / gardener_mq2). Общей памяти с сервером нет: все данные
 * о саде садовник получает сообщениями от garden_server (очередь "<base>_q"
 * для запросов и "<base>_a<id>" для ответов). Номер садовника задаётся
 * при сборке: -DGARDENER_ID=0 или 1. */
#define _GNU_SOURCE
#include "simulation_internal.h"
#include "simulation.h"
#include "shared.h"
#include "mq_proto.h"
#include <mqueue.h>

#ifndef GARDENER_ID
#error "Укажите -DGARDENER_ID=0 или 1"
#endif

static const int me = GARDENER_ID;
static mqd_t q_req = (mqd_t)-1, q_rep = (mqd_t)-1;
static pid_t server_pid;
static int srv_stop;          /* сервер потребовал остановку (признак в ответах) */
static Gardener *g;           /* локальные данные садовника: маршрут, позиция, счётчики */

static int aborted(void) { return sig_stop || srv_stop; }

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

/* Пауза с проверкой остановки каждые ≤20 мс. 1 — отработана полностью. */
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

/* Отправка сообщения серверу (блокируется, если очередь заполнена). */
static int send_req(Msg *rq)
{
    rq->g = me;
    for (;;) {
        struct timespec ts;
        abs_deadline(&ts, 500);
        if (mq_timedsend(q_req, (const char *)rq, sizeof *rq, 0, &ts) == 0) return 1;
        if (errno == EINTR || errno == ETIMEDOUT) {
            if (server_pid > 0 && kill(server_pid, 0) < 0 && errno == ESRCH) break;
            continue;
        }
        break;
    }
    srv_stop = 1;
    return 0;
}

/* Запрос с ожиданием ответа; 0 — сервер недоступен. */
static int rpc(Msg *rq, Msg *rp)
{
    if (!send_req(rq)) return 0;
    for (;;) {
        struct timespec ts;
        abs_deadline(&ts, 500);
        ssize_t k = mq_timedreceive(q_rep, (char *)rp, sizeof *rp, NULL, &ts);
        if (k == (ssize_t)sizeof *rp) {
            if (rp->stop) srv_stop = 1;
            return 1;
        }
        if (errno == EINTR) continue;
        if (errno == ETIMEDOUT) {
            if (server_pid > 0 && kill(server_pid, 0) < 0 && errno == ESRCH) break;
            continue;
        }
        break;
    }
    srv_stop = 1;
    return 0;
}

/* Событие садовника: сервер печатает его с меткой времени. */
static void ev(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void ev(const char *fmt, ...)
{
    Msg m;
    memset(&m, 0, sizeof m);
    m.type = REQ_EVENT;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(m.data, sizeof m.data, fmt, ap);
    va_end(ap);
    send_req(&m);
}

/* Захват клетки: 1 — клетка теперь занята этим садовником. */
static int try_cell(int c, int wait)
{
    Msg rq, rp;
    memset(&rq, 0, sizeof rq);
    rq.type = REQ_TRY;
    rq.a = c;
    rq.b = wait;
    return rpc(&rq, &rp) && rp.a == 1;
}

/* Ожидание занятой клетки c: 1 — клетка захвачена, 0 — остановка. */
static int wait_enter(int c)
{
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    g->waits++;
    ev("клетка (%d,%d) занята другим садовником — ожидает освобождения", ROW(c), COL(c));
    for (;;) {
        if (try_cell(c, 1)) {
            clock_gettime(CLOCK_MONOTONIC, &t1);
            long ms = (long)((t1.tv_sec - t0.tv_sec) * 1000 + (t1.tv_nsec - t0.tv_nsec) / 1000000);
            g->wait_ms += ms;
            ev("дождался освобождения клетки (%d,%d), ждал %ld мс", ROW(c), COL(c), ms);
            return 1;
        }
        if (aborted()) return 0;
        struct timespec ts = {0, 10 * 1000000L};
        nanosleep(&ts, NULL);
    }
}

/* Переход в соседнюю клетку step (уже занята этим садовником). */
static void do_move(int step)
{
    int from = g->pos;
    g->moves++;
    g->since_progress++;
    ev("переходит (%d,%d) -> (%d,%d)", ROW(from), COL(from), ROW(step), COL(step));
    sleep_ms(g->move_ms);
    Msg rq, rp;
    memset(&rq, 0, sizeof rq);
    rq.type = REQ_MOVED;
    rq.a = from;
    rq.b = step;
    rpc(&rq, &rp);
    g->pos = step;
}

/* Путь к клетке target. 1 — пришёл, 0 — клетка недостижима, -1 — остановка. */
static int walk_to(int target)
{
    int other = 1 - me;
    while (g->pos != target) {
        if (aborted()) return -1;
        if (g->since_progress > 4 * NC + 16) {
            Msg h;
            memset(&h, 0, sizeof h);
            h.type = REQ_HALT;
            h.a = HALT_LIVELOCK;
            send_req(&h);
            srv_stop = 1;
            return -1;
        }
        int sstep = bfs_next(g->pos, target, -1);
        if (sstep < 0) return 0;
        int step = sstep, sblocked = 0;
        if (cfg.bypass[me]) { /* обход разрешён: узнаём у сервера клетки соседа */
            Msg rq, rp;
            memset(&rq, 0, sizeof rq);
            rq.type = REQ_OCC;
            if (!rpc(&rq, &rp)) return -1;
            for (int i = 0; i < NC; i++) owner[i] = -1;
            if (rp.a >= 0) owner[rp.a] = other;
            if (rp.b >= 0) owner[rp.b] = other;
            int alt = bfs_next(g->pos, target, other);
            sblocked = (owner[sstep] == other);
            if (alt >= 0) step = alt;
        }
        if (try_cell(step, 0)) {
            if (step != sstep && sblocked) {
                g->bypasses++;
                ev("клетка (%d,%d) занята — обходит через (%d,%d)", ROW(sstep), COL(sstep),
                   ROW(step), COL(step));
            }
            do_move(step);
            continue;
        }
        if (!wait_enter(step)) return -1;
        do_move(step);
    }
    return 1;
}

/* Следующая необработанная клетка маршрута. -1 — маршрут исчерпан. */
static int next_target(void)
{
    while (g->idx < NC) {
        int c = route[me][g->idx];
        Msg rq, rp;
        memset(&rq, 0, sizeof rq);
        rq.type = REQ_CELLINFO;
        rq.a = c;
        if (!rpc(&rq, &rp)) return -1;
        if (rp.a) {
            ev("пропускает недоступную клетку (%d,%d) [%c]", ROW(c), COL(c), rp.a);
            g->skipped_obst++;
        } else if (rp.b != CS_TODO) {
            ev("пропускает клетку (%d,%d): %s", ROW(c), COL(c),
               rp.b == CS_DONE ? "уже обработана" : "её сейчас обрабатывает другой");
            g->skipped_done++;
        } else {
            return c;
        }
        g->idx++;
    }
    return -1;
}

/* Обработка клетки, в которой стоит садовник: запрос BEGIN -> пауза -> END. */
static void process_cell(void)
{
    int c = g->pos;
    Msg rq, rp;
    memset(&rq, 0, sizeof rq);
    rq.type = REQ_BEGIN;
    rq.a = c;
    if (!rpc(&rq, &rp) || rp.a != 1) return;
    int full = sleep_ms(g->work_ms);
    memset(&rq, 0, sizeof rq);
    rq.type = REQ_END;
    rq.a = c;
    rq.b = full;
    rpc(&rq, &rp);
    if (full) {
        g->processed++;
        g->since_progress = 0;
    }
}

static void usage(const char *prog)
{
    char b[512];
    int n = snprintf(b, sizeof b,
        "Садовник %d — независимый процесс (%s).\n"
        "Использование: %s [-n ИМЯ]\n"
        "  -n ИМЯ  базовое имя IPC, как у garden_server (по умолчанию /garden)\n",
        GARDENER_ID + 1, IMPL_NAME, prog);
    write_all(1, b, (size_t)n);
}

/* Открытие очередей; сервер мог ещё не стартовать — ждём до 30 с. */
static int open_queues(const char *base)
{
    char nm[128];
    for (int i = 0; i < 300 && !sig_stop; i++) {
        snprintf(nm, sizeof nm, "%s_q", base);
        q_req = mq_open(nm, O_WRONLY);
        if (q_req != (mqd_t)-1) {
            snprintf(nm, sizeof nm, "%s_a%d", base, me);
            q_rep = mq_open(nm, O_RDONLY);
            if (q_rep != (mqd_t)-1) return 1;
            mq_close(q_req);
            q_req = (mqd_t)-1;
        }
        struct timespec ts = {0, 100 * 1000000L};
        nanosleep(&ts, NULL);
    }
    err_msg("Не найдены очереди сообщений '%s_*': запустите garden_server с тем же -n", base);
    return 0;
}

int main(int argc, char **argv)
{
    int opt;
    opterr = 0;
    snprintf(cfg.base, sizeof cfg.base, "/garden");
    install_signal_handlers();
    while ((opt = getopt(argc, argv, "n:h")) != -1) {
        if (opt == 'n') snprintf(cfg.base, sizeof cfg.base, "%s", optarg);
        else if (opt == 'h') { usage(argv[0]); return 0; }
        else { err_msg("Неверный параметр (справка: -h)"); return 1; }
    }
    const char *base = ipc_base();

    if (!open_queues(base)) return sig_stop ? 3 : 1;
    if (!prims_attach(base)) return 1;

    /* Знакомство с сервером: получаем параметры и карту препятствий. */
    Msg rq, rp;
    memset(&rq, 0, sizeof rq);
    rq.type = REQ_HELLO;
    rq.a = (int)getpid();
    if (!rpc(&rq, &rp)) {
        err_msg("Сервер не ответил");
        return 1;
    }
    W = rp.v[V_W];
    H = rp.v[V_H];
    NC = W * H;
    server_pid = rp.v[V_SRVPID];
    cfg.corner[me] = rp.v[V_CORNER];
    cfg.cols[me] = rp.v[V_COLS];
    cfg.bypass[me] = rp.v[V_BYPASS];
    cfg.view = rp.v[V_VIEW];
    memcpy(obst, rp.data, (size_t)NC);
    gen_route(me, cfg.corner[me], cfg.cols[me]);
    g = &gd[me];
    g->id = me;
    g->pos = rp.v[V_START];
    g->move_ms = rp.v[V_MOVE];
    g->work_ms = rp.v[V_WORK];
    for (int i = 0; i < NC; i++) owner[i] = -1; /* рабочий массив для поиска обхода */

    ready_signal(); /* сообщаем серверу о готовности */
    int normal = 0;
    if (start_wait()) {
        ev("приступил к работе (процесс %d), стартовая клетка (%d,%d)", (int)getpid(),
           ROW(g->pos), COL(g->pos));
        while (!aborted()) {
            int t = next_target();
            if (t < 0) {
                normal = !aborted();
                break;
            }
            int r = walk_to(t);
            if (r < 0) break;
            if (r == 0) {
                ev("клетка (%d,%d) недостижима — пропуск", ROW(t), COL(t));
                g->unreachable++;
            } else {
                process_cell();
            }
            g->idx++;
        }
    }

    /* Сообщаем итоги серверу и освобождаем клетку. */
    memset(&rq, 0, sizeof rq);
    rq.type = REQ_DONE;
    rq.a = normal;
    rq.b = sig_stop;
    rq.c = g->pos;
    rq.v[D_MOVES] = g->moves;
    rq.v[D_WAITS] = g->waits;
    rq.v[D_BYPASSES] = g->bypasses;
    rq.v[D_SKIP_OBST] = g->skipped_obst;
    rq.v[D_SKIP_DONE] = g->skipped_done;
    rq.v[D_UNREACH] = g->unreachable;
    rq.v[D_WAIT_MS] = (int)g->wait_ms;
    rpc(&rq, &rp);
    done_signal();

    mq_close(q_req);
    mq_close(q_rep);
    prims_close();
    return 0;
}
