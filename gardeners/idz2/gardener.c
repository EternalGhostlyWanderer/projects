#define _GNU_SOURCE
#include "simulation_internal.h"
#include "gardener.h"

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

#ifndef USE_CV
static sem_t csem[MAX_CELLS]; /* владение клеткой: 1 — свободна          */
static sem_t start_sem;       /* «ворота» старта                          */
static sem_t done_sem;        /* садовник завершил работу                 */

void prims_init(void)
{
    for (int i = 0; i < NC; i++) sem_init(&csem[i], 0, 1);
    sem_init(&start_sem, 0, 0);
    sem_init(&done_sem, 0, 0);
}
void prims_destroy(void)
{
    for (int i = 0; i < NC; i++) sem_destroy(&csem[i]);
    sem_destroy(&start_sem);
    sem_destroy(&done_sem);
}
/* Неблокирующий захват клетки. */
int cell_try(int g, int c)
{
    if (sem_trywait(&csem[c]) != 0) return 0;
    pthread_mutex_lock(&mtx);
    owner[c] = g;
    waiting_for[g] = -1;
    pthread_mutex_unlock(&mtx);
    return 1;
}
/* Ожидание клетки не дольше ms мс. */
int cell_wait_slice(int g, int c, int ms)
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
void cell_release(int g, int c)
{
    (void)g;
    pthread_mutex_lock(&mtx);
    owner[c] = -1;
    check_invariants_locked("освобождение клетки", 0);
    pthread_mutex_unlock(&mtx);
    sem_post(&csem[c]);
}
void start_open(void) { for (int i = 0; i < NG; i++) sem_post(&start_sem); }
void start_wait(void) { while (sem_wait(&start_sem) < 0 && errno == EINTR) {} }
void done_signal(void) { sem_post(&done_sem); }
int done_wait_slice(int ms)
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

void prims_init(void) { pthread_barrier_init(&start_barrier, NULL, NG + 1); }
void prims_destroy(void) { pthread_barrier_destroy(&start_barrier); }
int cell_try(int g, int c)
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
int cell_wait_slice(int g, int c, int ms)
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
void cell_release(int g, int c)
{
    (void)g;
    pthread_mutex_lock(&mtx);
    owner[c] = -1;
    check_invariants_locked("освобождение клетки", 0);
    pthread_cond_broadcast(&cell_cv);
    pthread_mutex_unlock(&mtx);
}
void start_open(void) { pthread_barrier_wait(&start_barrier); }
void start_wait(void) { pthread_barrier_wait(&start_barrier); }
void done_signal(void)
{
    pthread_mutex_lock(&mtx);
    done_count++;
    pthread_cond_signal(&done_cv);
    pthread_mutex_unlock(&mtx);
}
int done_wait_slice(int ms)
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
    emit_g(me, "прибыл в (%d,%d)", ROW(step), COL(step));
    check_invariants_locked("переход садовника", 0);
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
        if (cfg.bypass[me]) { /* обход разрешён: ищем путь мимо занятых клеток */
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
    if (aborted()) { /* после остановки новую обработку не начинаем */
        pthread_mutex_unlock(&mtx);
        return;
    }
    if (cell_state[c] != CS_TODO) {
        emit_g(me, "клетка (%d,%d) уже обработана — пропуск", ROW(c), COL(c));
        pthread_mutex_unlock(&mtx);
        return;
    }
    if (completed_once[c] != 0) {
        check_invariants_locked("повторная обработка клетки", 0);
        pthread_mutex_unlock(&mtx);
        return;
    }
    cell_state[c] = CS_WORK;
    emit_g(me, "начал обработку клетки (%d,%d), %d мс", ROW(c), COL(c), g->work_ms);
    check_invariants_locked("начало обработки клетки", 0);
    pthread_mutex_unlock(&mtx);

    int full = sleep_ms(g->work_ms);

    pthread_mutex_lock(&mtx);
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
    pthread_mutex_unlock(&mtx);
}

void *gardener_main(void *arg)
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
    else if (atomic_load(&halt_reason) == HALT_INVARIANT) g->end_text = "прерван: нарушение инварианта";
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
