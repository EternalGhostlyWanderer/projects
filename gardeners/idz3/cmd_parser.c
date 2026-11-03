#define _GNU_SOURCE
#include "simulation_internal.h"
#include "cmd_parser.h"
#include "config_reader.h"
#include <ctype.h>
#include <poll.h>

#define MAX_TRIES 5          /* число неверных вводов подряд до значения по умолчанию */

static const char *const corner_code[4] = {"TL", "TR", "BL", "BR"};

static void usage(const char *prog)
{
    char b[8192];
    int n = snprintf(b, sizeof b,
        "Нелюдимые садовники (вариант 15), процессы. Сборка: " IMPL_NAME "\n"
        "Использование: %s [параметры]   (без параметров в терминале — диалог)\n"
        "  -W N       ширина сада, клеток (по умолчанию 10, максимум %d)\n"
        "  -H N       высота сада (по умолчанию 6, максимум %d)\n"
        "  -p P       доля недоступных клеток, %% (по умолчанию 15)\n"
        "  -r SEED    зерно генератора препятствий (по умолчанию — от времени)\n"
        "  -f FILE    файл конфигурации: h w r s1 t1 s2 t2 d1 d2 [x1 y1 x2 y2] [rows|columns] [x y ...]\n"
        "             (параметры командной строки перекрывают значения из файла)\n"
        "  -m FILE    карта из файла ('#' камень, '~' пруд, остальное — свободно);\n"
        "             при -m параметры -W, -H, -p, -r не действуют\n"
        "  -a R,C     стартовая клетка садовника 1 (с 1); по умолчанию угол маршрута\n"
        "  -b R,C     стартовая клетка садовника 2\n"
        "  -A СПЕЦ    маршрут садовника 1: УГОЛ[:rows|cols], УГОЛ = TL,TR,BL,BR\n"
        "             (по умолчанию TL:rows — змейка по строкам из левого верхнего)\n"
        "  -B СПЕЦ    маршрут садовника 2 (по умолчанию BR:rows)\n"
        "  -t A,B     время перехода между клетками, мс, 0..%d (по умолчанию 150,150)\n"
        "  -k A,B     время обработки клетки, мс, 0..%d (по умолчанию 300,300)\n"
        "  -o         разрешить обход занятой клетки (по умолчанию — только ждать)\n"
        "  -v N       0 события; 1 +карта после обработки (умолч.); 2 +после переходов\n"
        "  -l FILE    файл лога (по умолчанию garden.log)\n"
        "  -n ИМЯ     базовое имя объектов IPC (shm, семафоры, очереди), по умолчанию /garden_<pid>;\n"
        "             для независимых процессов у всех программ должно быть одинаковым\n"
        "  -i         принудительный диалог ввода параметров (значения командной\n"
        "             строки становятся значениями по умолчанию диалога)\n"
        "  -h         эта справка\n"
        "Сигналы: SIGINT/SIGTERM — корректная остановка (в том числе во время диалога);\n"
        "         SIGUSR1 — показать карту.\n"
        "Коды выхода: 0 всё обработано; 1 ошибка параметров; 2 тупик/необработанные/\n"
        "             нарушение инварианта; 3 прервано сигналом (в т.ч. при вводе).\n",
        prog, MAX_W, MAX_H, MAX_TIME_MS, MAX_TIME_MS);
    if (n > (int)sizeof b - 1) n = (int)sizeof b - 1; /* не читать за границей буфера */
    write_all(1, b, (size_t)n);
}

/* ------------------------------------------------------------------ */
/* Чтение строк диалога: устойчиво к сигналам, EOF и закрытому stdin    */
/* ------------------------------------------------------------------ */

static int dlg_eof = 0;        /* вход закончился: остальное — по умолчанию */
static int dlg_cancelled = 0;  /* прервано сигналом остановки */

static void dputs(const char *s) { write_all(1, s, strlen(s)); }

/* Читает строку из stdin. Возвращает длину (>=0), -1 — конец входных данных
 * (в т.ч. закрытый дескриптор), -2 — получен сигнал остановки.
 * Ожидание идёт через poll() с тайм-аутом 100 мс, поэтому сигнал, пришедший
 * до входа в read(), не теряется. */
static int read_line(char *buf, size_t n)
{
    size_t i = 0;
    int got = 0;
    if (n == 0) return -1;
    for (;;) {
        if (sig_stop) {
            buf[i] = 0;
            return -2;
        }
        struct pollfd p = {.fd = 0, .events = POLLIN};
        int r = poll(&p, 1, 100);
        if (r == 0) continue;                 /* тайм-аут: перепроверим sig_stop */
        if (r < 0 && errno == EINTR) continue;
        char ch;
        ssize_t k = read(0, &ch, 1);
        if (k < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (k <= 0) {                         /* EOF или ошибка чтения */
            if (!got) {
                buf[0] = 0;
                return -1;
            }
            break;                            /* последняя строка без '\n' */
        }
        got = 1;
        if (ch == '\n') break;
        if (i + 1 < n) buf[i++] = ch;         /* лишние символы длинной строки отбрасываем */
    }
    buf[i] = 0;
    return (int)i;
}

static char *trim(char *s)
{
    while (*s == ' ' || *s == '\t' || *s == '\r') s++;
    size_t l = strlen(s);
    while (l > 0 && (s[l - 1] == ' ' || s[l - 1] == '\t' || s[l - 1] == '\r')) s[--l] = 0;
    return s;
}

/* Один запрос. 1 — строка получена; 0 — ввод закончился или прерван. */
static int ask(const char *q, const char *defs, char *line, size_t n)
{
    char msg[320];
    if (dlg_eof || dlg_cancelled) return 0;
    int k = snprintf(msg, sizeof msg, "%s [%s]: ", q, defs);
    if (k > (int)sizeof msg - 1) k = (int)sizeof msg - 1;
    write_all(1, msg, (size_t)k);
    int r = read_line(line, n);
    if (r == -2) {
        dlg_cancelled = 1;
        dputs("\nВвод прерван сигналом — параметры не приняты\n");
        return 0;
    }
    if (r == -1) {
        dlg_eof = 1;
        dputs("\nВвод прерван (конец входных данных) — остальные параметры по умолчанию\n");
        return 0;
    }
    if (!isatty(0)) { /* ввод не с терминала: повторяем ответ, чтобы вывод читался */
        write_all(1, line, strlen(line));
        write_all(1, "\n", 1);
    }
    return 1;
}

static int ask_int(const char *q, int def, int lo, int hi)
{
    char line[128], defs[32], msg[200];
    snprintf(defs, sizeof defs, "%d", def);
    for (int t = 0; t < MAX_TRIES; t++) {
        if (!ask(q, defs, line, sizeof line)) return def;
        char *s = trim(line);
        if (!*s) return def;
        char *e;
        errno = 0;
        long v = strtol(s, &e, 10);
        if (*e == '\0' && errno == 0 && v >= lo && v <= hi) return (int)v;
        snprintf(msg, sizeof msg, "  ожидается целое число от %d до %d\n", lo, hi);
        dputs(msg);
    }
    snprintf(msg, sizeof msg, "  слишком много неверных вводов — значение по умолчанию: %d\n", def);
    dputs(msg);
    return def;
}

static void ask_str(const char *q, const char *def, char *out, size_t n)
{
    char line[256];
    if (!ask(q, def, line, sizeof line)) {
        snprintf(out, n, "%s", def);
        return;
    }
    char *s = trim(line);
    snprintf(out, n, "%s", *s ? s : def);
}

/* ------------------------------------------------------------------ */
/* Разбор значений (при ошибке выходные параметры не изменяются)        */
/* ------------------------------------------------------------------ */

static int parse_route(const char *s, int *corner, int *cols)
{
    char a[8] = {0}, b[8] = {0};
    int k = sscanf(s, " %7[A-Za-z] : %7[A-Za-z]", a, b);
    if (k < 1) return 0;
    for (char *p = a; *p; p++) if (*p >= 'a' && *p <= 'z') *p -= 32;
    for (char *p = b; *p; p++) if (*p >= 'A' && *p <= 'Z') *p += 32;
    int cn = -1, co;
    for (int i = 0; i < 4; i++) if (!strcmp(a, corner_code[i])) cn = i;
    if (cn < 0) return 0;
    if (k == 1 || !strcmp(b, "rows") || !strcmp(b, "r")) co = 0;
    else if (!strcmp(b, "cols") || !strcmp(b, "c")) co = 1;
    else return 0;
    *corner = cn;
    *cols = co;
    return 1;
}

/* Одно число — одинаковое значение для обоих садовников; «A,B» — два значения. */
static int parse_pair(const char *s, int *a, int *b)
{
    char *e;
    errno = 0;
    long x = strtol(s, &e, 10);
    if (e == s || errno) return 0;
    long y = x;
    while (isspace((unsigned char)*e)) e++;
    if (*e == ',') {
        const char *p = e + 1;
        errno = 0;
        y = strtol(p, &e, 10);
        if (e == p || errno) return 0;
        while (isspace((unsigned char)*e)) e++;
    }
    if (*e != '\0') return 0;
    if (x < 0 || y < 0 || x > MAX_TIME_MS || y > MAX_TIME_MS) return 0;
    *a = (int)x;
    *b = (int)y;
    return 1;
}

/* «R,C»: диапазон проверяется позже (в build_world), здесь только формат. */
static int parse_rc(const char *s, int *r, int *c)
{
    char *e;
    errno = 0;
    long x = strtol(s, &e, 10);
    if (e == s || errno) return 0;
    while (isspace((unsigned char)*e)) e++;
    if (*e != ',') return 0;
    const char *p = e + 1;
    errno = 0;
    long y = strtol(p, &e, 10);
    if (e == p || errno) return 0;
    while (isspace((unsigned char)*e)) e++;
    if (*e != '\0') return 0;
    if (x < -1000000 || x > 1000000 || y < -1000000 || y > 1000000) return 0;
    *r = (int)x;
    *c = (int)y;
    return 1;
}

/* ------------------------------------------------------------------ */
/* Диалог настройки. 0 — завершён, 1 — завершён, но ввод оборвался     */
/* (EOF), -1 — отменён сигналом.                                        */
/* ------------------------------------------------------------------ */
static int interactive(void)
{
    char s[256], q[200], def[64];
    static char mapname[256];

    dlg_eof = 0;
    dlg_cancelled = 0;
    dputs("=== Диалог настройки (Enter — значение в скобках) ===\n");
    ask_str("Файл карты (- : случайный сад)", cfg.map_file[0] ? cfg.map_file : "-", s, sizeof s);
    if (strcmp(s, "-") != 0) {
        snprintf(mapname, sizeof mapname, "%s", s);
        snprintf(cfg.map_file, sizeof cfg.map_file, "%s", mapname);
    } else {
        cfg.map_file[0] = 0;
        cfg.w = ask_int("Ширина сада", cfg.w, 1, MAX_W);
        cfg.h = ask_int("Высота сада", cfg.h, 1, MAX_H);
        cfg.obst_pct = ask_int("Доля недоступных клеток, %", cfg.obst_pct, 0, 90);
        cfg.seed = (unsigned)ask_int("Зерно генератора (0 — от времени)", (int)cfg.seed, 0, 2000000000);
    }
    for (int g = 0; g < NG; g++) {
        snprintf(q, sizeof q, "Маршрут садовника %d (УГОЛ:rows|cols, угол TL/TR/BL/BR)", g + 1);
        snprintf(def, sizeof def, "%s:%s", corner_code[cfg.corner[g]], cfg.cols[g] ? "cols" : "rows");
        for (int t = 0; t < MAX_TRIES; t++) {
            ask_str(q, def, s, sizeof s);
            if (parse_route(s, &cfg.corner[g], &cfg.cols[g])) break;
            if (dlg_eof || dlg_cancelled) break;
            dputs("  неверная спецификация маршрута\n");
        }
        snprintf(q, sizeof q, "Стартовая клетка садовника %d (строка,столбец; - угол маршрута)", g + 1);
        if (cfg.start_set[g]) snprintf(def, sizeof def, "%d,%d", cfg.start_r[g], cfg.start_c[g]);
        else snprintf(def, sizeof def, "-");
        ask_str(q, def, s, sizeof s);
        int r, c;
        if (!strcmp(s, "-")) cfg.start_set[g] = 0;
        else if (parse_rc(s, &r, &c)) {
            cfg.start_r[g] = r;
            cfg.start_c[g] = c;
            cfg.start_set[g] = 1;
        } else if (!dlg_eof && !dlg_cancelled) {
            dputs("  не распознано — оставлено прежнее значение\n");
        }
        snprintf(q, sizeof q, "Время перехода садовника %d, мс", g + 1);
        cfg.move_ms[g] = ask_int(q, cfg.move_ms[g], 0, MAX_TIME_MS);
        snprintf(q, sizeof q, "Время обработки клетки садовником %d, мс", g + 1);
        cfg.work_ms[g] = ask_int(q, cfg.work_ms[g], 0, MAX_TIME_MS);
    }
    int detour = ask_int("Разрешить обход занятой клетки (0 нет, 1 да)", (cfg.bypass[0] || cfg.bypass[1]) ? 1 : 0, 0, 1);
    cfg.bypass[0] = cfg.bypass[1] = detour;
    cfg.view = ask_int("Режим карты (0 события, 1 после обработки, 2 после переходов)", cfg.view, 0, 2);
    if (dlg_cancelled) return -1;
    return dlg_eof ? 1 : 0;
}

static int to_int(const char *s, int lo, int hi, const char *what)
{
    char *e;
    errno = 0;
    long v = strtol(s, &e, 10);
    if (*s == 0 || *e || errno == ERANGE || v < lo || v > hi) {
        err_msg("Параметр %s: ожидается число от %d до %d, получено '%s'", what, lo, hi, s);
        exit(1);
    }
    return (int)v;
}

void config_defaults(void)
{
    cfg = (Config){
        .w = 10,
        .h = 6,
        .obst_pct = 15,
        .seed = 0,
        .corner = {0, 3},
        .cols = {0, 0},
        .move_ms = {150, 150},
        .work_ms = {300, 300},
        .bypass = {0, 0},
        .view = 1
    };
    snprintf(cfg.log_path, sizeof cfg.log_path, "garden.log");
}

int cmd_parser_parse(int argc, char **argv)
{
    int force_dialog = 0;
    int random_params = 0; /* заданы ли -W/-H/-p/-r (не действуют вместе с -m) */
    int opt;

    int file_loaded = 0;

    opterr = 0; /* сообщения об ошибках печатаем сами */

    /* Файл конфигурации читаем до разбора остальных параметров:
     * значения командной строки перекрывают значения из файла. */
    for (int i = 1; i < argc; i++) {
        const char *path = NULL;
        if (strcmp(argv[i], "-f") == 0) {
            if (i + 1 >= argc) break; /* getopt сообщит о нехватке аргумента */
            path = argv[++i];
        } else if (strncmp(argv[i], "-f", 2) == 0) {
            path = argv[i] + 2;
        }
        if (path != NULL) {
            if (!load_config_file(path)) return 1;
            file_loaded = 1;
        }
    }

    while ((opt = getopt(argc, argv, "f:W:H:p:r:m:a:b:A:B:t:k:ov:l:n:ih")) != -1) {
        switch (opt) {
        case 'f':
            if (!file_loaded) { err_msg("-f: укажите файл отдельным аргументом: -f ФАЙЛ"); return 1; }
            break; /* файл уже прочитан */
        case 'W': cfg.w = to_int(optarg, 1, MAX_W, "-W"); random_params = 1; break;
        case 'H': cfg.h = to_int(optarg, 1, MAX_H, "-H"); random_params = 1; break;
        case 'p': cfg.obst_pct = to_int(optarg, 0, 90, "-p"); random_params = 1; break;
        case 'r': cfg.seed = (unsigned)to_int(optarg, 0, 2000000000, "-r"); random_params = 1; break;
        case 'm': snprintf(cfg.map_file, sizeof cfg.map_file, "%s", optarg); break;
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
            if (!parse_pair(optarg, &cfg.move_ms[0], &cfg.move_ms[1])) { err_msg("-t ожидает A,B (мс, 0..%d)", MAX_TIME_MS); return 1; }
            break;
        case 'k':
            if (!parse_pair(optarg, &cfg.work_ms[0], &cfg.work_ms[1])) { err_msg("-k ожидает A,B (мс, 0..%d)", MAX_TIME_MS); return 1; }
            break;
        case 'o': cfg.bypass[0] = cfg.bypass[1] = 1; break;
        case 'v': cfg.view = to_int(optarg, 0, 2, "-v"); break;
        case 'l': snprintf(cfg.log_path, sizeof cfg.log_path, "%s", optarg); break;
        case 'n': snprintf(cfg.base, sizeof cfg.base, "%s", optarg); break;
        case 'i': force_dialog = 1; break;
        case 'h': usage(argv[0]); return 2;
        default:
            if (optopt) err_msg("Неизвестный параметр или не хватает аргумента: -%c (справка: -h)", optopt);
            else err_msg("Неверный параметр (справка: -h)");
            return 1;
        }
    }
    if (optind < argc) {
        err_msg("Лишний аргумент '%s' (справка: -h)", argv[optind]);
        return 1;
    }
    if (cfg.map_file[0] && random_params)
        err_msg("Предупреждение: -W, -H, -p и -r не действуют при загрузке карты из файла (-m)");

    if (force_dialog || (argc == 1 && isatty(0))) {
        int r = interactive();
        print_req = 0; /* SIGUSR1, пришедший во время диалога, не относится к модели */
        if (r < 0) return 3; /* диалог отменён сигналом: модель не запускается */
    }
    if (cfg.seed == 0) cfg.seed = (unsigned)time(NULL);
    return 0;
}
