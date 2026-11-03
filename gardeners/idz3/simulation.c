#define _GNU_SOURCE
#include "simulation_internal.h"
#include "simulation.h"
#include "shared.h"

volatile sig_atomic_t print_req = 0;
int log_fd = -1;
static volatile sig_atomic_t local_stop = 0; /* сигнал остановки, полученный ЭТИМ процессом */

/* Проверка инвариантов общего состояния. Вызывается только под мьютексом-семафором,
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

/* Обработчик сигналов. Флаг остановки лежит в разделяемой памяти, поэтому
 * сигнал, полученный любым процессом, останавливает всех участников.
 * Повторный сигнал в том же процессе — аварийный выход с удалением IPC. */
static void on_signal(int s)
{
    if (s == SIGUSR1) {
        print_req = 1;
        return;
    }
    if (local_stop) {
        cleanup_ipc_on_signal(); /* sem_unlink / shm_unlink (только у создателя) */
        _exit(128 + s);
    }
    local_stop = s;
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

/* Итоги и диагностика. Вызывается после завершения всех садовников.
 * Возвращает код выхода. */
int print_summary(void)
{
    lock();
    check_invariants_locked("после завершения процессов", 1);
    unlock();

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
    if (halt == HALT_CRASH) {
        say("Причина завершения: аварийно завершился процесс садовника");
        code = 2;
    } else if (sig) {
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
        say("Садовник %d (процесс %d): обработано=%d, переходов=%d, ожиданий=%d (%ld мс), обходов=%d, "
            "пропущено препятствий=%d, пропущено обработанных=%d, недостижимых=%d; %s",
            g + 1, (int)p->pid, p->processed, p->moves, p->waits, p->wait_ms, p->bypasses,
            p->skipped_obst, p->skipped_done, p->unreachable, end_text(p->end_code));
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

/* Аварийное завершение процесса садовника g: освобождаем его клетки и
 * останавливаем остальных. Мьютекс мог остаться захваченным погибшим процессом. */
void handle_crash(int g, const char *how)
{
    lock_recover();
    Gardener *p = &gd[g];
    int exp = HALT_NONE;
    atomic_compare_exchange_strong(&halt_reason, &exp, HALT_CRASH);
    emit("ОШИБКА: процесс садовника %d (pid %d) %s", g + 1, (int)p->pid, how);
    for (int c = 0; c < NC; c++)
        if (owner[c] == g) owner[c] = -1;
    if (cell_state[p->pos >= 0 ? p->pos : 0] == CS_WORK && p->pos >= 0)
        cell_state[p->pos] = CS_TODO; /* обработка не закончена */
    p->pos = -1;
    p->end_code = END_CRASH;
    p->finished = 1;
    unlock();
}

/* Баннер с параметрами запуска. */
void print_banner(const char *base)
{
    say("==== Нелюдимые садовники. Сборка: %s ====", IMPL_NAME);
    say("Сад %d x %d (строк x столбцов), доступных клеток %d, препятствий %d%s%s",
        H, W, NFREE, NC - NFREE, cfg.map_file[0] ? ", карта: " : "",
        cfg.map_file[0] ? cfg.map_file : "");
    if (!cfg.map_file[0]) say("Доля препятствий %d%%, зерно %u", cfg.obst_pct, cfg.seed);
    for (int g = 0; g < NG; g++)
        say("Садовник %d: старт (%d,%d), маршрут: %s угол, змейка по %s; "
            "переход %d мс, обработка %d мс",
            g + 1, ROW(start_cell[g]), COL(start_cell[g]), corner_name[cfg.corner[g]],
            cfg.cols[g] ? "столбцам" : "строкам", cfg.move_ms[g], cfg.work_ms[g]);
    say("Обход занятой клетки: садовник 1 — %s, садовник 2 — %s; режим карты: %d; лог: %s",
        cfg.bypass[0] ? "разрешён" : "запрещён (только ожидание)",
        cfg.bypass[1] ? "разрешён" : "запрещён (только ожидание)", cfg.view,
        log_fd >= 0 ? cfg.log_path : "-");
    say("IPC: базовое имя объектов %s", base);
    say("Легенда: # камень, ~ пруд, . не обработано, + обработано, 1/2 садовники");
}

#ifndef IPC_MQ
/* Освобождение всех объектов IPC и закрытие журнала. */
static void teardown(void)
{
    prims_close();
    prims_unlink();
    shared_unlink();
    shared_detach();
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

    /* Позиции садовников нужны уже начальной карте (show_map читает gd[].pos). */
    for (int g = 0; g < NG; g++) {
        gd[g].id = g;
        gd[g].pid = 0;
        gd[g].pos = start_cell[g];
        gd[g].move_ms = cfg.move_ms[g];
        gd[g].work_ms = cfg.work_ms[g];
    }

    /* Разделяемая память и семафоры создаются родительским процессом. */
    const char *base = ipc_base();
    if (!shared_create(base)) return 1;
    if (!prims_create(base)) {
        shared_unlink();
        shared_detach();
        return 1;
    }
    atomic_store(&S->world_ready, 1);

    log_fd = open(cfg.log_path, O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0644);
    if (log_fd < 0)
        err_msg("Предупреждение: лог '%s' не открыт: %s", cfg.log_path, strerror(errno));

    install_signal_handlers(); /* повторная установка безвредна */

    print_banner(base);
    show_map("начальное состояние сада");

    for (int g = 0; g < NG; g++) {
        if (!cell_try(g, start_cell[g])) {
            err_msg("Не удалось зарезервировать стартовую клетку садовника %d", g + 1);
            teardown();
            return 1;
        }
    }
    lock();
    check_invariants_locked("начальная расстановка", 0);
    unlock();

    int remaining = 0;
#ifdef INDEPENDENT
    /* Садовники — независимые программы gardener1 и gardener2: ждём,
     * пока обе присоединятся к shm и сообщат о готовности. */
    say("Ожидаю запуска садовников:  ./gardener1 -n %s   и   ./gardener2 -n %s", base, base);
    int ready = 0;
    while (ready < NG && !sig_stop) {
        if (ready_wait_slice(100)) ready++;
        if (print_req) {
            print_req = 0;
            lock();
            show_map("состояние по запросу (SIGUSR1)");
            unlock();
        }
    }
    remaining = ready;
    if (ready == NG) start_open(); /* одновременный старт обоих процессов */
#else
    pid_t pids[NG] = {0, 0};
    int created = 0;
    for (int g = 0; g < NG; g++) {
        pid_t p = fork();
        if (p < 0) {
            err_msg("fork садовника %d: %s", g + 1, strerror(errno));
            int exp = HALT_NONE;
            atomic_compare_exchange_strong(&halt_reason, &exp, HALT_CRASH);
            break;
        }
        if (p == 0) { /* дочерний процесс: садовник g */
            gardener_run(g);
            prims_close();
            shared_detach();
            if (log_fd >= 0) close(log_fd);
            _exit(0);
        }
        pids[g] = p;
        created++;
    }
    remaining = created;
    start_open(); /* одновременный старт: семафор-«ворота» */
#endif

    /* Родитель: ждёт завершения садовников, показывает карту по SIGUSR1,
     * следит за аварийной гибелью процессов. */
    int dead[NG] = {0, 0};
    while (remaining > 0) {
        if (done_wait_slice(100)) remaining--;
        if (print_req) {
            print_req = 0;
            lock();
            show_map("состояние по запросу (SIGUSR1)");
            unlock();
        }
        for (int g = 0; g < NG; g++) {
            if (dead[g] || gd[g].finished) continue;
#ifdef INDEPENDENT
            pid_t p = gd[g].pid;
            if (p > 0 && kill(p, 0) < 0 && errno == ESRCH) {
                dead[g] = 1;
                handle_crash(g, "исчез без штатного завершения");
                remaining--;
            }
#else
            if (pids[g] <= 0) continue;
            int st;
            pid_t r = waitpid(pids[g], &st, WNOHANG);
            if (r == pids[g]) {
                pids[g] = -1;
                if (!gd[g].finished) {
                    dead[g] = 1;
                    handle_crash(g, WIFSIGNALED(st) ? "убит сигналом" : "завершился с ошибкой");
                    remaining--;
                }
            }
#endif
        }
    }
#ifndef INDEPENDENT
    for (int g = 0; g < NG; g++)
        if (pids[g] > 0) waitpid(pids[g], NULL, 0); /* не оставляем зомби */
#endif

    int code = print_summary();
    teardown();
    return code;
}
#endif /* IPC_MQ: в версии с очередями simulation_run лежит в simulation_mq.c */
