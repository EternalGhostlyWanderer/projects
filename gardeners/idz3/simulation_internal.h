#ifndef SIMULATION_INTERNAL_H
#define SIMULATION_INTERNAL_H

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <semaphore.h>
#include <signal.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

// Предельные размеры сада и число садовников
#define MAX_W 60
#define MAX_H 40
#define MAX_CELLS (MAX_W * MAX_H)
#define NG 2

// Верхняя граница времени перехода и обработки клетки, мс
#define MAX_TIME_MS 100000

// Состояния клетки, причины остановки и причины завершения садовника
enum { CS_TODO = 0, CS_WORK, CS_DONE, CS_OBST };
enum { HALT_NONE = 0, HALT_DEADLOCK, HALT_LIVELOCK, HALT_INVARIANT, HALT_CRASH };
enum { END_NONE = 0, END_NORMAL, END_SIGNAL, END_DEADLOCK, END_INVARIANT, END_LIVELOCK, END_CRASH };

// Название сборки (вид семафоров и способ запуска процессов)
#if defined(IPC_MQ)
#define IMPL_NAME "независимые процессы + очередь сообщений POSIX + именованные семафоры"
#elif defined(INDEPENDENT)
#define IMPL_NAME "независимые процессы + shm POSIX + именованные семафоры"
#elif defined(SEM_UNNAMED)
#define IMPL_NAME "fork + shm POSIX + неименованные семафоры (sem_init в shm)"
#else
#define IMPL_NAME "fork + shm POSIX + именованные семафоры (sem_open)"
#endif

// Параметры запуска (командная строка, файл конфигурации, диалог).
// Структура лежит в разделяемой памяти, поэтому в ней нет указателей.
typedef struct {
    int w, h;                       // размеры сада
    int obst_pct;                   // доля случайных препятствий, %
    unsigned seed;                  // зерно генератора (0 — по времени)
    char map_file[256];             // файл карты ("" — случайный сад)
    int start_set[NG];              // стартовая клетка задана явно
    int start_r[NG], start_c[NG];   // стартовая клетка (с 1)
    int corner[NG];                 // угол маршрута: 0 TL, 1 TR, 2 BL, 3 BR
    int cols[NG];                   // 0 — змейка по строкам, 1 — по столбцам
    int move_ms[NG];                // время перехода, мс
    int work_ms[NG];                // время обработки клетки, мс
    int bypass[NG];                 // обход занятой клетки разрешён
    int view;                       // 0 события, 1 карта после обработки, 2 после переходов
    char log_path[256];             // файл журнала
    char base[64];                  // базовое имя объектов IPC ("" — "/garden_<pid>")
    int obst_n;                     // число препятствий из файла конфигурации
    int obst_r[MAX_CELLS];          // их координаты (с 1)
    int obst_c[MAX_CELLS];
} Config;

// Данные садовника (каждый садовник — отдельный процесс)
typedef struct {
    int id;
    pid_t pid;                      // идентификатор процесса садовника
    int finished;                   // садовник завершил работу (под мьютексом)
    int pos;                        // текущая клетка (-1 после завершения)
    int idx;                        // позиция в маршруте
    int move_ms, work_ms;
    int since_progress;             // переходов с последней обработки клетки
    int processed, moves, waits, bypasses;
    int skipped_obst, skipped_done, unreachable;
    long wait_ms;
    int end_code;                   // причина завершения (END_*)
} Gardener;

// Всё общее состояние модели. В режимах с shm это единый объект в
// разделяемой памяти POSIX, отображённый во все процессы; изменяется
// только под мьютексом-семафором (см. lock()/unlock()).
typedef struct {
    Config cfg;
    int W, H, NC, NFREE;
    char obst[MAX_CELLS];
    int cell_state[MAX_CELLS];
    int completed_once[MAX_CELLS];  // 1, если клетка уже обработана
    int owner[MAX_CELLS];           // кто занимает клетку (-1 — никто)
    int waiting_for[NG];
    int route[NG][MAX_CELLS];
    int start_cell[NG];
    Gardener gd[NG];
    atomic_int sig_stop;            // номер сигнала остановки (виден всем процессам)
    atomic_int halt_reason;
    atomic_int world_ready;         // мир построен и примитивы созданы
    int invariant_checks;
    int invariant_violations;
    struct timespec t_start;
    // Неименованные семафоры (режим SEM_UNNAMED); в именованном режиме не используются
    sem_t u_mtx, u_start, u_ready, u_done;
    sem_t u_cell[MAX_CELLS];
} Shared;

// Общее состояние. До создания shm указывает на локальную копию.
extern Shared *S;

#define cfg (S->cfg)
#define W (S->W)
#define H (S->H)
#define NC (S->NC)
#define NFREE (S->NFREE)
#define obst (S->obst)
#define cell_state (S->cell_state)
#define completed_once (S->completed_once)
#define owner (S->owner)
#define waiting_for (S->waiting_for)
#define route (S->route)
#define start_cell (S->start_cell)
#define gd (S->gd)
#define sig_stop (S->sig_stop)
#define halt_reason (S->halt_reason)
#define invariant_checks (S->invariant_checks)
#define invariant_violations (S->invariant_violations)
#define t_start (S->t_start)

// Номер строки и столбца клетки для вывода (с 1)
#define ROW(c) ((c) / W + 1)
#define COL(c) ((c) % W + 1)

extern volatile sig_atomic_t print_req;
extern int log_fd;
extern const char *corner_name[4];

// Журнал и вывод
void write_all(int fd, const char *b, size_t n);
void out_raw(const char *b, size_t n);
void err_msg(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
double elapsed(void);
void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void emit_g(int id, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
const char *end_text(int code);

// Проверка инвариантов (только при захваченном мьютексе); final_check=1 — в конце
int check_invariants_locked(const char *where, int final_check);

// Карта и чтение файлов
void show_map(const char *title);
int load_map(const char *path);
int load_config_file(const char *path);
int build_world(void);
void flood(int start, char *seen);

// Разбор аргументов
void config_defaults(void);
int cmd_parser_parse(int argc, char **argv);

// Разделяемая память (shared.c)
int shared_create(const char *base);   // создать shm и перенести в неё состояние
int shared_attach(const char *base);   // присоединиться к shm (независимый процесс)
void shared_detach(void);
void shared_unlink(void);              // удалить shm (только создатель)

// Семафоры и поведение садовников (gardener.c, sync.c)
int prims_create(const char *base);
int prims_attach(const char *base);
void prims_close(void);
void prims_unlink(void);
void lock(void);
void unlock(void);
void lock_recover(void);
int cell_try(int g, int c);
int cell_wait_slice(int g, int c, int ms);
void cell_release(int g, int c);
void start_open(void);
int start_wait(void);
void ready_signal(void);
int ready_wait_slice(int ms);
int ready_try(void);
int done_try(void);
void done_signal(void);
int done_wait_slice(int ms);
void gardener_run(int id);
int bfs_next(int from, int to, int avoid_owner);   // первый шаг кратчайшего пути (-1 — нет)

// Сигналы и общие функции процессов (simulation.c)
int simulation_run(void);
void install_signal_handlers(void);
int print_summary(void);
void cleanup_ipc_on_signal(void);
void print_banner(const char *base);
void handle_crash(int g, const char *how);
extern void (*ipc_extra_cleanup)(void);     // очистка очередей при аварийном выходе
void gen_route(int g, int corner, int cols);

#endif
