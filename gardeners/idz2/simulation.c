#define _GNU_SOURCE
#include "simulation_internal.h"
#include "simulation.h"

Config cfg;
int W, H, NC, NFREE;
char obst[MAX_CELLS];
int cell_state[MAX_CELLS];
int completed_once[MAX_CELLS];
int owner[MAX_CELLS];
int waiting_for[NG];
int route[NG][MAX_CELLS];
int start_cell[NG];
Gardener gd[NG];
pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;
/* Флаг остановки пишет обработчик сигнала (главный поток), а читают потоки
 * садовников. volatile sig_atomic_t не защищает от гонки между потоками,
 * поэтому используется атомарная переменная (lock-free, допустима в обработчике). */
atomic_int sig_stop;
volatile sig_atomic_t print_req = 0;
atomic_int halt_reason;
int log_fd = -1;
struct timespec t_start;
int invariant_checks = 0;
int invariant_violations = 0;

/* Проверка инвариантов общего состояния. Вызывается только под mtx,
 * поэтому состояние не меняется посреди проверки. */
int check_invariants_locked(const char *where, int final_check)
{
    int owned_count[NG] = {0, 0};
    int working_count[NG] = {0, 0};
    int done_count = 0;
    int processed_sum = 0;
    char problem[256] = "";

    invariant_checks++;

    /* Проверяем состояние каждой клетки и корректность её владельца. */
    for (int c = 0; c < NC; c++) {
        if (owner[c] < -1 || owner[c] >= NG) {
            snprintf(problem, sizeof problem,
                     "клетка (%d,%d) имеет неизвестного владельца %d",
                     ROW(c), COL(c), owner[c]);
            break;
        }

        if (owner[c] >= 0) {
            owned_count[owner[c]]++;
            if (obst[c]) {
                snprintf(problem, sizeof problem,
                         "садовник %d занял недоступную клетку (%d,%d)",
                         owner[c] + 1, ROW(c), COL(c));
                break;
            }
        }

        if (obst[c] && cell_state[c] != CS_OBST) {
            snprintf(problem, sizeof problem,
                     "препятствие (%d,%d) имеет неверное состояние клетки",
                     ROW(c), COL(c));
            break;
        }
        if (!obst[c] && cell_state[c] == CS_OBST) {
            snprintf(problem, sizeof problem,
                     "доступная клетка (%d,%d) помечена как препятствие",
                     ROW(c), COL(c));
            break;
        }

        if (cell_state[c] == CS_WORK) {
            int g = owner[c];
            if (g < 0 || gd[g].pos != c) {
                snprintf(problem, sizeof problem,
                         "клетка (%d,%d) обрабатывается без стоящего на ней садовника",
                         ROW(c), COL(c));
                break;
            }
            working_count[g]++;
        }

        if (cell_state[c] == CS_DONE) {
            done_count++;
            if (completed_once[c] != 1) {
                snprintf(problem, sizeof problem,
                         "клетка (%d,%d) завершена, но счётчик обработки неверен",
                         ROW(c), COL(c));
                break;
            }
        } else if (completed_once[c] != 0) {
            snprintf(problem, sizeof problem,
                     "клетка (%d,%d) отмечена обработанной, но состояние не DONE",
                     ROW(c), COL(c));
            break;
        }
    }

    /* Каждая активная позиция должна быть доступной и занята своим садовником. */
    if (problem[0] == '\0') {
        for (int g = 0; g < NG; g++) {
            processed_sum += gd[g].processed;
            if (gd[g].pos >= 0) {
                if (final_check) {
                    snprintf(problem, sizeof problem,
                             "после завершения садовник %d всё ещё занимает клетку", g + 1);
                    break;
                }
                if (gd[g].pos >= NC) {
                    snprintf(problem, sizeof problem,
                             "позиция садовника %d выходит за границы сада", g + 1);
                    break;
                }
                if (obst[gd[g].pos]) {
                    snprintf(problem, sizeof problem,
                             "садовник %d находится на препятствии (%d,%d)",
                             g + 1, ROW(gd[g].pos), COL(gd[g].pos));
                    break;
                }
                if (owner[gd[g].pos] != g) {
                    snprintf(problem, sizeof problem,
                             "текущая клетка садовника %d не закреплена за ним", g + 1);
                    break;
                }
            } else if (gd[g].pos != -1) {
                snprintf(problem, sizeof problem,
                         "у садовника %d некорректная отметка завершения", g + 1);
                break;
            }

            /* На переходе временно зарезервированы старая и новая клетки. */
            if (owned_count[g] > 2) {
                snprintf(problem, sizeof problem,
                         "садовник %d одновременно зарезервировал больше двух клеток", g + 1);
                break;
            }
            if (working_count[g] > 1) {
                snprintf(problem, sizeof problem,
                         "садовник %d одновременно обрабатывает несколько клеток", g + 1);
                break;
            }
        }
    }

    if (problem[0] == '\0' && gd[0].pos >= 0 && gd[0].pos == gd[1].pos) {
        snprintf(problem, sizeof problem,
                 "оба садовника находятся в клетке (%d,%d)",
                 ROW(gd[0].pos), COL(gd[0].pos));
    }

    if (problem[0] == '\0' && done_count != processed_sum) {
        snprintf(problem, sizeof problem,
                 "число обработанных клеток (%d) не совпадает со статистикой садовников (%d)",
                 done_count, processed_sum);
    }

    if (problem[0] == '\0' && done_count > NFREE) {
        snprintf(problem, sizeof problem,
                 "обработано клеток больше, чем доступно в саду");
    }

    if (problem[0] == '\0' && final_check) {
        for (int c = 0; c < NC; c++) {
            if (owner[c] != -1) {
                snprintf(problem, sizeof problem,
                         "после завершения осталась занята клетка (%d,%d)",
                         ROW(c), COL(c));
                break;
            }
            if (cell_state[c] == CS_WORK) {
                snprintf(problem, sizeof problem,
                         "после завершения осталась незаконченная обработка (%d,%d)",
                         ROW(c), COL(c));
                break;
            }
        }
    }

    if (problem[0] != '\0') {
        int previous = atomic_exchange(&halt_reason, HALT_INVARIANT);
        if (previous != HALT_INVARIANT) {
            invariant_violations++;
            emit("НАРУШЕНИЕ ИНВАРИАНТА в точке '%s': %s", where, problem);
        }
        return 0;
    }

    return 1;
}

static void on_signal(int s)
{
    if (s == SIGUSR1) {
        print_req = 1;
        return;
    }
    if (sig_stop) _exit(128 + s); /* повторный сигнал остановки — аварийный выход */
    sig_stop = s;
}

/* Обработчики без SA_RESTART: блокирующие вызовы прерываются сигналом. */
void install_signal_handlers(void)
{
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGUSR1, &sa, NULL);
    signal(SIGPIPE, SIG_IGN); /* закрытый канал вывода не должен убивать программу */
}

/* Итоги и диагностика. Вызывается после join. Возвращает код выхода. */
static int print_summary(void)
{
    pthread_mutex_lock(&mtx);
    check_invariants_locked("после завершения потоков", 1);
    pthread_mutex_unlock(&mtx);

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
    } else if (halt == HALT_INVARIANT) {
        say("Причина завершения: нарушен инвариант модели; выполнение остановлено");
        code = 2;
    } else if (left == 0) {
        /* Тупик, замеченный после обработки последней достижимой клетки,
         * уже не означает неуспех: работа по саду полностью завершена. */
        say("Причина завершения: все достижимые клетки обработаны");
    } else if (halt == HALT_DEADLOCK) {
        say("Причина завершения: тупик — садовники взаимно ждут друг друга, обход невозможен");
        code = 2;
    } else if (halt == HALT_LIVELOCK) {
        say("Причина завершения: зацикливание — обход невозможно продолжить");
        code = 2;
    } else {
        say("Причина завершения: обход остановлен, остались необработанные клетки");
        code = 2;
    }
    say("Время моделирования: %.3f с", elapsed());
    say("Проверки инвариантов: %d; нарушений: %d", invariant_checks, invariant_violations);
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

int simulation_run(void)
{
    atomic_store(&halt_reason, HALT_NONE);
    invariant_checks = 0;
    invariant_violations = 0;

    clock_gettime(CLOCK_MONOTONIC, &t_start);
    if (!build_world()) return 1;

    /* Позиции садовников нужны уже начальной карте (show_map читает gd[].pos). */
    for (int g = 0; g < NG; g++) {
        gd[g].id = g;
        gd[g].pos = start_cell[g];
        gd[g].move_ms = cfg.move_ms[g];
        gd[g].work_ms = cfg.work_ms[g];
    }

    log_fd = open(cfg.log_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (log_fd < 0)
        err_msg("Предупреждение: лог '%s' не открыт: %s", cfg.log_path, strerror(errno));

    install_signal_handlers(); /* повторная установка безвредна */

    say("==== Нелюдимые садовники. Сборка: %s ====", IMPL_NAME);
    say("Сад %d x %d (строк x столбцов), доступных клеток %d, препятствий %d%s%s",
        H, W, NFREE, NC - NFREE, cfg.map_file ? ", карта: " : "",
        cfg.map_file ? cfg.map_file : "");
    if (!cfg.map_file) say("Доля препятствий %d%%, зерно %u", cfg.obst_pct, cfg.seed);
    for (int g = 0; g < NG; g++)
        say("Садовник %d: старт (%d,%d), маршрут: %s угол, змейка по %s; "
            "переход %d мс, обработка %d мс",
            g + 1, ROW(start_cell[g]), COL(start_cell[g]), corner_name[cfg.corner[g]],
            cfg.cols[g] ? "столбцам" : "строкам", cfg.move_ms[g], cfg.work_ms[g]);
    say("Обход занятой клетки: садовник 1 — %s, садовник 2 — %s; режим карты: %d; лог: %s",
        cfg.bypass[0] ? "разрешён" : "запрещён (только ожидание)",
        cfg.bypass[1] ? "разрешён" : "запрещён (только ожидание)", cfg.view,
        log_fd >= 0 ? cfg.log_path : "-");
    say("Легенда: # камень, ~ пруд, . не обработано, + обработано, 1/2 садовники");
    show_map("начальное состояние сада");

    prims_init();
    for (int g = 0; g < NG; g++) {
        if (!cell_try(g, start_cell[g])) {
            err_msg("Не удалось зарезервировать стартовую клетку садовника %d", g + 1);
            prims_destroy();
            if (log_fd >= 0) close(log_fd);
            return 1;
        }
    }
    pthread_mutex_lock(&mtx);
    check_invariants_locked("начальная расстановка", 0);
    pthread_mutex_unlock(&mtx);

    /* Потоки садовников наследуют маску: блокируем сигналы, чтобы их
     * принимал только главный поток. */
    sigset_t set, old;
    sigemptyset(&set);
    sigaddset(&set, SIGINT);
    sigaddset(&set, SIGTERM);
    sigaddset(&set, SIGUSR1);
    pthread_sigmask(SIG_BLOCK, &set, &old);
    int created = 0;
    for (int g = 0; g < NG; g++) {
        if (pthread_create(&gd[g].th, NULL, gardener_main, &gd[g]) != 0) {
            err_msg("Не удалось создать поток садовника %d", g + 1);
            break;
        }
        created++;
    }
    pthread_sigmask(SIG_SETMASK, &old, NULL);
    if (created < NG) {
        /* Неустранимая системная ошибка. Созданные потоки ждут общего старта
         * (барьер не прерывается pthread_cancel), поэтому не уничтожаем примитивы:
         * процесс завершается, ОС освободит потоки вместе с ним. */
        if (log_fd >= 0) close(log_fd);
        return 1;
    }

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
