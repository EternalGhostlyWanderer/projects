#ifndef SIMULATION_INTERNAL_H
#define SIMULATION_INTERNAL_H

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

// Предельные размеры сада и число садовников
#define MAX_W 60
#define MAX_H 40
#define MAX_CELLS (MAX_W * MAX_H)
#define NG 2

// Верхняя граница времени перехода и обработки клетки, мс
#define MAX_TIME_MS 100000

// Состояния клетки и причины аварийного завершения
enum { CS_TODO = 0, CS_WORK, CS_DONE, CS_OBST };
enum { HALT_NONE = 0, HALT_DEADLOCK, HALT_LIVELOCK, HALT_INVARIANT };

#ifdef USE_CV
#define IMPL_NAME "мьютекс + условные переменные + барьер"
#else
#define IMPL_NAME "мьютекс + семафоры (sem_t)"
#endif

// Параметры запуска (командная строка, файл конфигурации, диалог)
typedef struct {
    int w, h;                       // размеры сада
    int obst_pct;                   // доля случайных препятствий, %
    unsigned seed;                  // зерно генератора (0 — по времени)
    const char *map_file;           // файл карты (NULL — случайный сад)
    int start_set[NG];              // стартовая клетка задана явно
    int start_r[NG], start_c[NG];   // стартовая клетка (с 1)
    int corner[NG];                 // угол маршрута: 0 TL, 1 TR, 2 BL, 3 BR
    int cols[NG];                   // 0 — змейка по строкам, 1 — по столбцам
    int move_ms[NG];                // время перехода, мс
    int work_ms[NG];                // время обработки клетки, мс
    int bypass[NG];                 // обход занятой клетки разрешён
    int view;                       // 0 события, 1 карта после обработки, 2 после переходов
    const char *log_path;           // файл журнала
    int obst_n;                     // число препятствий из файла конфигурации
    int obst_r[MAX_CELLS];          // их координаты (с 1)
    int obst_c[MAX_CELLS];
} Config;

// Данные садовника (каждый садовник — отдельный поток)
typedef struct {
    int id;
    pthread_t th;
    int pos;                        // текущая клетка (-1 после завершения)
    int idx;                        // позиция в маршруте
    int move_ms, work_ms;
    int since_progress;             // переходов с последней обработки клетки
    int processed, moves, waits, bypasses;
    int skipped_obst, skipped_done, unreachable;
    long wait_ms;
    const char *end_text;           // причина завершения
} Gardener;

// Номер строки и столбца клетки для вывода (с 1)
#define ROW(c) ((c) / W + 1)
#define COL(c) ((c) % W + 1)

// Общее состояние модели; изменяется под мьютексом mtx
extern Config cfg;
extern int W, H, NC, NFREE;
extern char obst[MAX_CELLS];
extern int cell_state[MAX_CELLS];
extern int completed_once[MAX_CELLS];   // 1, если клетка уже обработана
extern int owner[MAX_CELLS];            // кто занимает клетку (-1 — никто)
extern int waiting_for[NG];
extern int route[NG][MAX_CELLS];
extern int start_cell[NG];
extern Gardener gd[NG];
extern pthread_mutex_t mtx;
extern atomic_int sig_stop;             // номер сигнала остановки; атомарный, т.к. читается из потоков садовников
extern volatile sig_atomic_t print_req;
extern atomic_int halt_reason;
extern int log_fd;
extern struct timespec t_start;
extern int invariant_checks;
extern int invariant_violations;
extern const char *corner_name[4];

// Журнал и вывод
void write_all(int fd, const char *b, size_t n);
void out_raw(const char *b, size_t n);
void err_msg(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
double elapsed(void);
void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void emit(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void emit_g(int id, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

// Проверка инвариантов (только при захваченном mtx); final_check=1 — после join
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

// Поведение садовников и синхронизация
void prims_init(void);
void prims_destroy(void);
int cell_try(int g, int c);
int cell_wait_slice(int g, int c, int ms);
void cell_release(int g, int c);
void start_open(void);
void start_wait(void);
void done_signal(void);
int done_wait_slice(int ms);
void *gardener_main(void *arg);

// Главный цикл имитации и обработчики сигналов
int simulation_run(void);
void install_signal_handlers(void);

#endif
