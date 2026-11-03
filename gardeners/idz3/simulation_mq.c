/* Версия с очередями сообщений POSIX: процесс-сервер сада (garden_server).
 * Состояние сада принадлежит только серверу (обычная память, без shm);
 * садовники — независимые процессы gardener_mq1/gardener_mq2 — шлют ему
 * запросы в очередь "<base>_q" и читают ответы из "<base>_a<g>".
 * Именованные семафоры используются для общего старта, готовности
 * и сообщения о завершении. */
#define _GNU_SOURCE
#include "simulation_internal.h"
#include "simulation.h"
#include "shared.h"
#include "mq_proto.h"
#include <mqueue.h>

#ifdef IPC_MQ

static mqd_t q_req = (mqd_t)-1;
static mqd_t q_rep[NG] = {(mqd_t)-1, (mqd_t)-1};
static char name_req[128], name_rep[NG][128];
static pid_t mq_creator = 0;

static int aborted(void) { return sig_stop || atomic_load(&halt_reason); }

/* Удаление имён очередей (безопасно повторно; только создатель). */
static void unlink_queues(void)
{
    if (mq_creator != getpid()) return;
    mq_unlink(name_req);
    for (int g = 0; g < NG; g++) mq_unlink(name_rep[g]);
    mq_creator = 0;
}

static int create_queues(const char *base)
{
    struct mq_attr at;
    memset(&at, 0, sizeof at);
    at.mq_maxmsg = 10;
    at.mq_msgsize = (long)sizeof(Msg);
    snprintf(name_req, sizeof name_req, "%s_q", base);
    for (int g = 0; g < NG; g++) snprintf(name_rep[g], sizeof name_rep[g], "%s_a%d", base, g);
    mq_unlink(name_req);
    for (int g = 0; g < NG; g++) mq_unlink(name_rep[g]);
    mq_creator = getpid();
    q_req = mq_open(name_req, O_CREAT | O_EXCL | O_RDONLY, 0600, &at);
    if (q_req == (mqd_t)-1) {
        err_msg("mq_open('%s'): %s", name_req, strerror(errno));
        return 0;
    }
    for (int g = 0; g < NG; g++) {
        q_rep[g] = mq_open(name_rep[g], O_CREAT | O_EXCL | O_WRONLY, 0600, &at);
        if (q_rep[g] == (mqd_t)-1) {
            err_msg("mq_open('%s'): %s", name_rep[g], strerror(errno));
            return 0;
        }
    }
    return 1;
}

static void close_queues(void)
{
    if (q_req != (mqd_t)-1) mq_close(q_req);
    for (int g = 0; g < NG; g++)
        if (q_rep[g] != (mqd_t)-1) mq_close(q_rep[g]);
    q_req = (mqd_t)-1;
    q_rep[0] = q_rep[1] = (mqd_t)-1;
    unlink_queues();
}

/* Ответ садовнику g; в каждом ответе передаётся признак остановки. */
static void reply(int g, Msg *m)
{
    m->g = g;
    m->stop = aborted() ? 1 : 0;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += 2;
    mq_timedsend(q_rep[g], (const char *)m, sizeof *m, 0, &ts);
}

static int deadlock_between(int me)
{
    int ot = 1 - me, wm = waiting_for[me], wo = waiting_for[ot];
    if (wm < 0 || wo < 0) return 0;
    return owner[wm] == ot && owner[wo] == me;
}

/* ---- обработчики запросов ---- */

static void on_hello(Msg *rq)
{
    int g = rq->g;
    gd[g].pid = rq->a;
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_HELLO;
    rp.v[V_W] = W;
    rp.v[V_H] = H;
    rp.v[V_START] = start_cell[g];
    rp.v[V_CORNER] = cfg.corner[g];
    rp.v[V_COLS] = cfg.cols[g];
    rp.v[V_MOVE] = cfg.move_ms[g];
    rp.v[V_WORK] = cfg.work_ms[g];
    rp.v[V_BYPASS] = cfg.bypass[g];
    rp.v[V_VIEW] = cfg.view;
    rp.v[V_SRVPID] = (int)getpid();
    memcpy(rp.data, obst, (size_t)NC);
    reply(g, &rp);
}

static void on_cellinfo(Msg *rq)
{
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_CELLINFO;
    rp.a = obst[rq->a];
    rp.b = cell_state[rq->a];
    reply(rq->g, &rp);
}

static void on_occ(Msg *rq)
{
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_OCC;
    int other = 1 - rq->g, n = 0;
    int cells[2] = {-1, -1};
    for (int c = 0; c < NC && n < 2; c++)
        if (owner[c] == other) cells[n++] = c;
    rp.a = cells[0];
    rp.b = cells[1];
    reply(rq->g, &rp);
}

static void on_try(Msg *rq)
{
    int g = rq->g, c = rq->a;
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_TRY;
    if (aborted()) {
        rp.a = 0;
    } else if (owner[c] < 0) {
        owner[c] = g;
        waiting_for[g] = -1;
        rp.a = 1;
    } else if (rq->b) {
        waiting_for[g] = c;
        if (deadlock_between(g)) {
            int exp = HALT_NONE;
            if (atomic_compare_exchange_strong(&halt_reason, &exp, HALT_DEADLOCK))
                emit("ТУПИК: садовник %d ждёт клетку (%d,%d), занятую садовником %d, "
                     "а тот ждёт клетку (%d,%d), занятую первым",
                     g + 1, ROW(c), COL(c), 2 - g, ROW(waiting_for[1 - g]),
                     COL(waiting_for[1 - g]));
            waiting_for[g] = -1;
        }
    }
    reply(g, &rp);
}

static void on_moved(Msg *rq)
{
    int g = rq->g, from = rq->a, step = rq->b;
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_MOVED;
    gd[g].pos = step;
    emit_g(g, "прибыл в (%d,%d)", ROW(step), COL(step));
    check_invariants_locked("переход садовника", 0);
    if (cfg.view >= 2) show_map("после перехода");
    owner[from] = -1;
    check_invariants_locked("освобождение клетки", 0);
    rp.a = 1;
    reply(g, &rp);
}

static void on_begin(Msg *rq)
{
    int g = rq->g, c = rq->a;
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_BEGIN;
    if (aborted()) {
        /* после остановки новую обработку не начинаем */
    } else if (cell_state[c] != CS_TODO) {
        emit_g(g, "клетка (%d,%d) уже обработана — пропуск", ROW(c), COL(c));
    } else if (completed_once[c] != 0) {
        check_invariants_locked("повторная обработка клетки", 0);
    } else {
        cell_state[c] = CS_WORK;
        emit_g(g, "начал обработку клетки (%d,%d), %d мс", ROW(c), COL(c), gd[g].work_ms);
        check_invariants_locked("начало обработки клетки", 0);
        rp.a = 1;
    }
    reply(g, &rp);
}

static void on_end(Msg *rq)
{
    int g = rq->g, c = rq->a;
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_END;
    if (!rq->b) {
        cell_state[c] = CS_TODO; /* прервано — клетка остаётся необработанной */
        emit_g(g, "обработка клетки (%d,%d) прервана", ROW(c), COL(c));
    } else {
        completed_once[c] = 1;
        cell_state[c] = CS_DONE;
        gd[g].processed++;
        emit_g(g, "закончил обработку клетки (%d,%d)", ROW(c), COL(c));
        if (cfg.view >= 1) show_map("клетка обработана");
    }
    check_invariants_locked("окончание обработки клетки", 0);
    rp.a = 1;
    reply(g, &rp);
}

static void on_halt(Msg *rq)
{
    int exp = HALT_NONE;
    if (atomic_compare_exchange_strong(&halt_reason, &exp, rq->a) && rq->a == HALT_LIVELOCK)
        emit_g(rq->g, "много переходов без обработки клеток — зацикливание");
}

static void on_done(Msg *rq)
{
    int g = rq->g;
    Gardener *p = &gd[g];
    p->moves = rq->v[D_MOVES];
    p->waits = rq->v[D_WAITS];
    p->bypasses = rq->v[D_BYPASSES];
    p->skipped_obst = rq->v[D_SKIP_OBST];
    p->skipped_done = rq->v[D_SKIP_DONE];
    p->unreachable = rq->v[D_UNREACH];
    p->wait_ms = rq->v[D_WAIT_MS];
    waiting_for[g] = -1;
    if (rq->b && !sig_stop) sig_stop = rq->b; /* сигнал получил садовник: останавливаем всех */
    if (rq->a) p->end_code = END_NORMAL;
    else if (sig_stop) p->end_code = END_SIGNAL;
    else if (atomic_load(&halt_reason) == HALT_DEADLOCK) p->end_code = END_DEADLOCK;
    else if (atomic_load(&halt_reason) == HALT_INVARIANT) p->end_code = END_INVARIANT;
    else if (atomic_load(&halt_reason) == HALT_CRASH) p->end_code = END_CRASH;
    else p->end_code = END_LIVELOCK;
    int last = p->pos;
    p->pos = -1;
    emit_g(g, "завершает работу (%s), освобождает клетку (%d,%d)", end_text(p->end_code),
           ROW(last), COL(last));
    if (cfg.view >= 1) show_map("садовник ушёл");
    owner[last] = -1;
    check_invariants_locked("освобождение клетки", 0);
    p->finished = 1;
    Msg rp;
    memset(&rp, 0, sizeof rp);
    rp.type = REQ_DONE;
    rp.a = 1;
    reply(g, &rp);
}

static void dispatch(Msg *rq)
{
    rq->data[MQ_DATA - 1] = 0;
    if (rq->g < 0 || rq->g >= NG) return;
    switch (rq->type) {
    case REQ_HELLO: on_hello(rq); break;
    case REQ_CELLINFO: if (rq->a >= 0 && rq->a < NC) on_cellinfo(rq); break;
    case REQ_OCC: on_occ(rq); break;
    case REQ_TRY: if (rq->a >= 0 && rq->a < NC) on_try(rq); break;
    case REQ_MOVED:
        if (rq->a >= 0 && rq->a < NC && rq->b >= 0 && rq->b < NC) on_moved(rq);
        break;
    case REQ_BEGIN: if (rq->a >= 0 && rq->a < NC) on_begin(rq); break;
    case REQ_END: if (rq->a >= 0 && rq->a < NC) on_end(rq); break;
    case REQ_EVENT: emit_g(rq->g, "%s", rq->data); break;
    case REQ_HALT: on_halt(rq); break;
    case REQ_DONE: on_done(rq); break;
    default: break;
    }
}

static void teardown(void)
{
    close_queues();
    prims_close();
    prims_unlink();
    if (log_fd >= 0) {
        close(log_fd);
        log_fd = -1;
    }
}

int simulation_run(void)
{
    atomic_store(&halt_reason, HALT_NONE);
    invariant_checks = 0;
    invariant_violations = 0;
    clock_gettime(CLOCK_MONOTONIC, &t_start);
    if (!build_world()) return 1;

    for (int g = 0; g < NG; g++) {
        gd[g].id = g;
        gd[g].pid = 0;
        gd[g].pos = start_cell[g];
        gd[g].move_ms = cfg.move_ms[g];
        gd[g].work_ms = cfg.work_ms[g];
    }

    const char *base = ipc_base();
    if (!prims_create(base)) return 1;       /* именованные семафоры: старт, готовность, завершение */
    ipc_extra_cleanup = unlink_queues;       /* очереди удаляются и при аварийном выходе */
    if (!create_queues(base)) {
        teardown();
        return 1;
    }
    atomic_store(&S->world_ready, 1);

    log_fd = open(cfg.log_path, O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0644);
    if (log_fd < 0)
        err_msg("Предупреждение: лог '%s' не открыт: %s", cfg.log_path, strerror(errno));
    install_signal_handlers();

    print_banner(base);
    show_map("начальное состояние сада");
    for (int g = 0; g < NG; g++) owner[start_cell[g]] = g; /* стартовые клетки заняты */
    check_invariants_locked("начальная расстановка", 0);

    say("Ожидаю запуска садовников:  ./gardener_mq1 -n %s   и   ./gardener_mq2 -n %s", base, base);

    int ready = 0, started = 0, remaining = NG, dead[NG] = {0, 0};
    for (;;) {
        /* Один запрос из очереди (ожидание до 50 мс). */
        Msg rq;
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_nsec += 50 * 1000000L;
        if (ts.tv_nsec >= 1000000000L) {
            ts.tv_nsec -= 1000000000L;
            ts.tv_sec++;
        }
        ssize_t k = mq_timedreceive(q_req, (char *)&rq, sizeof rq, NULL, &ts);
        if (k == (ssize_t)sizeof rq) dispatch(&rq);

        while (!started && ready_try()) ready++;
        if (!started && (ready == NG || sig_stop)) {
            remaining = ready;
            start_open(); /* одновременный старт (при сигнале — чтобы никто не завис) */
            started = 1;
        }
        if (started)
            while (done_try()) remaining--;
        if (print_req) {
            print_req = 0;
            show_map("состояние по запросу (SIGUSR1)");
        }
        if (started) {
            for (int g = 0; g < NG; g++) {
                if (dead[g] || gd[g].finished || gd[g].pid <= 0) continue;
                if (kill(gd[g].pid, 0) < 0 && errno == ESRCH) {
                    dead[g] = 1;
                    handle_crash(g, "исчез без штатного завершения");
                    remaining--;
                }
            }
            if (remaining <= 0) break;
        } else if (sig_stop && ready == 0) {
            break;
        }
    }

    int code = print_summary();
    teardown();
    return code;
}

#endif /* IPC_MQ */
