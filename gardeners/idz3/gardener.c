#define _GNU_SOURCE
#include "simulation_internal.h"
#include "gardener.h"

/* Остановка запрошена сигналом (общий флаг в shm) либо причиной из модели. */
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

static const int DR[4] = {-1, 1, 0, 0};
static const int DC[4] = {0, 0, -1, 1};

/* Первый шаг кратчайшего пути from -> to по доступным клеткам.
 * avoid_owner >= 0: клетки, занятые этим садовником, считаются стеной
 * (тогда mtx должен быть захвачен). Возвращает -1, если пути нет. */
int bfs_next(int from, int to, int avoid_owner)
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
    lock();
    waiting_for[me] = c;
    g->waits++;
    emit_g(me, "клетка (%d,%d) занята другим садовником — ожидает освобождения",
           ROW(c), COL(c));
    unlock();
    for (;;) {
        if (cell_wait_slice(me, c, 20)) {
            lock();
            long ms = (long)((elapsed() - t0) * 1000.0);
            g->wait_ms += ms;
            emit_g(me, "дождался освобождения клетки (%d,%d), ждал %ld мс",
                   ROW(c), COL(c), ms);
            unlock();
            return 1;
        }
        lock();
        if (aborted()) {
            waiting_for[me] = -1;
            unlock();
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
            unlock();
            return 0;
        }
        unlock();
    }
}

/* Переход в соседнюю клетку step (она уже захвачена садовником).
 * Во время перехода занята и старая, и новая клетка. */
static void do_move(Gardener *g, int step)
{
    int me = g->id, from = g->pos;
    lock();
    g->moves++;
    g->since_progress++;
    emit_g(me, "переходит (%d,%d) -> (%d,%d)", ROW(from), COL(from), ROW(step),
           COL(step));
    unlock();
    sleep_ms(g->move_ms);
    lock();
    g->pos = step;
    emit_g(me, "прибыл в (%d,%d)", ROW(step), COL(step));
    check_invariants_locked("переход садовника", 0);
    if (cfg.view >= 2) show_map("после перехода");
    unlock();
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
            lock();
            if (atomic_compare_exchange_strong(&halt_reason, &exp, HALT_LIVELOCK))
                emit_g(me, "много переходов без обработки клеток — зацикливание");
            unlock();
            return -1;
        }
        int sstep = bfs_next(g->pos, target, -1); /* путь без учёта соседа */
        if (sstep < 0) return 0;
        int step = sstep, sblocked = 0;
        if (cfg.bypass[me]) { /* обход разрешён: ищем путь мимо занятых клеток */
            lock();
            int alt = bfs_next(g->pos, target, other);
            sblocked = (owner[sstep] == other);
            unlock();
            if (alt >= 0) step = alt;
        }
        if (cell_try(me, step)) {
            if (step != sstep && sblocked) {
                lock();
                g->bypasses++;
                emit_g(me, "клетка (%d,%d) занята — обходит через (%d,%d)",
                       ROW(sstep), COL(sstep), ROW(step), COL(step));
                unlock();
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
        lock();
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
            unlock();
            return c;
        }
        g->idx++;
        unlock();
    }
    return -1;
}

/* Обработка клетки, в которой стоит садовник. Клетка обрабатывается
 * не более одного раза: состояние TODO -> WORK -> DONE под мьютексом. */
static void process_cell(Gardener *g)
{
    int c = g->pos, me = g->id;
    lock();
    if (aborted()) { /* после остановки новую обработку не начинаем */
        unlock();
        return;
    }
    if (cell_state[c] != CS_TODO) {
        emit_g(me, "клетка (%d,%d) уже обработана — пропуск", ROW(c), COL(c));
        unlock();
        return;
    }
    if (completed_once[c] != 0) {
        check_invariants_locked("повторная обработка клетки", 0);
        unlock();
        return;
    }
    cell_state[c] = CS_WORK;
    emit_g(me, "начал обработку клетки (%d,%d), %d мс", ROW(c), COL(c), g->work_ms);
    check_invariants_locked("начало обработки клетки", 0);
    unlock();

    int full = sleep_ms(g->work_ms);

    lock();
    if (!full) {
        cell_state[c] = CS_TODO; /* прервано — клетка остаётся необработанной */
        emit_g(me, "обработка клетки (%d,%d) прервана", ROW(c), COL(c));
    } else {
        completed_once[c] = 1;
        cell_state[c] = CS_DONE;
        g->processed++;
        g->since_progress = 0;
        emit_g(me, "закончил обработку клетки (%d,%d)", ROW(c), COL(c));
        if (cfg.view >= 1) show_map("клетка обработана");
    }
    check_invariants_locked("окончание обработки клетки", 0);
    unlock();
}

/* Основной цикл садовника-процесса id. Вызывается после общего старта:
 * процесс уже присоединён к shm и открыл семафоры. */
void gardener_run(int id)
{
    Gardener *g = &gd[id];
    int me = id;
    int normal = 0;

    lock();
    g->pid = getpid();
    unlock();

    if (start_wait()) {
        lock();
        emit_g(me, "приступил к работе (процесс %d), стартовая клетка (%d,%d)",
               (int)getpid(), ROW(g->pos), COL(g->pos));
        unlock();

        while (!aborted()) {
            int t = next_target(g);
            if (t < 0) {
                normal = 1;
                break;
            }
            int r = walk_to(g, t);
            if (r < 0) break;
            if (r == 0) {
                lock();
                emit_g(me, "клетка (%d,%d) недостижима — пропуск", ROW(t), COL(t));
                g->unreachable++;
                unlock();
            } else {
                process_cell(g);
            }
            g->idx++;
        }
    }

    if (normal) g->end_code = END_NORMAL;
    else if (sig_stop) g->end_code = END_SIGNAL;
    else if (atomic_load(&halt_reason) == HALT_DEADLOCK) g->end_code = END_DEADLOCK;
    else if (atomic_load(&halt_reason) == HALT_INVARIANT) g->end_code = END_INVARIANT;
    else if (atomic_load(&halt_reason) == HALT_CRASH) g->end_code = END_CRASH;
    else g->end_code = END_LIVELOCK;

    /* Освобождаем ресурсы: клетку, в которой стоит садовник. */
    lock();
    int last = g->pos;
    g->pos = -1;
    emit_g(me, "завершает работу (%s), освобождает клетку (%d,%d)", end_text(g->end_code),
           ROW(last), COL(last));
    if (cfg.view >= 1) show_map("садовник ушёл");
    g->finished = 1;
    unlock();
    cell_release(me, last);
    done_signal();
}
