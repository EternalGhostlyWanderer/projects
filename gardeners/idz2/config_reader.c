#define _GNU_SOURCE
#include "simulation_internal.h"
#include "config_reader.h"
#include <math.h>
#include <sys/stat.h>

int load_map(const char *path)
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

/* ------------------------------------------------------------------ */
/* Файл конфигурации                                                   */
/* ------------------------------------------------------------------ */
/* Формат (значения разделены пробелами или переводами строк):
 *   h w r s1 t1 s2 t2 d1 d2 [x1 y1 x2 y2] [rows|columns] [x y ...]
 *   h, w    — высота и ширина сада;
 *   r       — доля случайных препятствий, 0..0.9 (0.15 = 15 %);
 *   s1, t1  — время перехода и обработки клетки садовника 1, мс;
 *   s2, t2  — то же для садовника 2;
 *   d1, d2  — обход занятой клетки разрешён (0/1/true/false) для садовников 1 и 2;
 *   x1 y1 x2 y2 — стартовые клетки (строка и столбец, с 1), необязательно;
 *   rows|columns — маршрут садовника 2, необязательно;
 *   x y ...  — клетки препятствий (строка и столбец, с 1), пары.
 * Всё от '#' до конца строки — комментарий. */

#define MAX_CONFIG_BYTES (1 << 20)
#define MAX_CONFIG_TOKENS (14 + 2 * MAX_CELLS)

static int cfg_int(const char *s, int *out)
{
    char *end;
    errno = 0;
    long v = strtol(s, &end, 10);
    if (errno == ERANGE || end == s || *end != '\0' || v < INT_MIN || v > INT_MAX) return 0;
    *out = (int)v;
    return 1;
}

static int cfg_double(const char *s, double *out)
{
    char *end;
    errno = 0;
    double v = strtod(s, &end);
    if (errno == ERANGE || end == s || *end != '\0' || !isfinite(v)) return 0;
    *out = v;
    return 1;
}

static int cfg_bool(const char *s, int *out)
{
    if (!strcmp(s, "0") || !strcmp(s, "false") || !strcmp(s, "FALSE") || !strcmp(s, "False")) {
        *out = 0;
        return 1;
    }
    if (!strcmp(s, "1") || !strcmp(s, "true") || !strcmp(s, "TRUE") || !strcmp(s, "True")) {
        *out = 1;
        return 1;
    }
    return 0;
}

static int cfg_route(const char *s)
{
    return !strcmp(s, "rows") || !strcmp(s, "columns");
}

/* Читает файл целиком через open()/fstat()/read(); NULL при ошибке. */
static char *read_whole_file(const char *path)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        err_msg("[Reader] Не могу открыть файл конфигурации '%s': %s", path, strerror(errno));
        return NULL;
    }
    struct stat st;
    if (fstat(fd, &st) < 0) {
        err_msg("[Reader] Ошибка получения размера файла '%s': %s", path, strerror(errno));
        close(fd);
        return NULL;
    }
    if (st.st_size <= 0) {
        err_msg("[Reader] Файл конфигурации '%s' пуст", path);
        close(fd);
        return NULL;
    }
    if (st.st_size > MAX_CONFIG_BYTES) {
        err_msg("[Reader] Файл конфигурации '%s' слишком велик", path);
        close(fd);
        return NULL;
    }
    size_t size = (size_t)st.st_size;
    char *buffer = malloc(size + 1);
    if (buffer == NULL) {
        err_msg("[Reader] Недостаточно памяти для чтения конфигурации");
        close(fd);
        return NULL;
    }
    size_t total = 0;
    while (total < size) {
        ssize_t n = read(fd, buffer + total, size - total);
        if (n < 0) {
            if (errno == EINTR) continue; /* прерывание системного вызова — повторяем */
            err_msg("[Reader] Ошибка чтения файла '%s': %s", path, strerror(errno));
            free(buffer);
            close(fd);
            return NULL;
        }
        if (n == 0) break;
        total += (size_t)n;
    }
    close(fd);
    if (total != size) {
        err_msg("[Reader] Файл '%s' прочитан не полностью", path);
        free(buffer);
        return NULL;
    }
    buffer[size] = '\0';
    return buffer;
}

int load_config_file(const char *path)
{
    char *buffer = read_whole_file(path);
    if (buffer == NULL) return 0;

    /* Комментарии: от '#' до конца строки заменяем пробелами. */
    for (char *p = buffer; *p; ) {
        if (*p == '#') {
            while (*p && *p != '\n') *p++ = ' ';
        } else {
            p++;
        }
    }

    /* Делим содержимое на значения. */
    static char *tokens[MAX_CONFIG_TOKENS];
    size_t count = 0;
    char *save = NULL;
    for (char *t = strtok_r(buffer, " \t\r\n", &save); t != NULL; t = strtok_r(NULL, " \t\r\n", &save)) {
        if (count >= MAX_CONFIG_TOKENS) {
            err_msg("[Reader] Слишком много значений в файле '%s'", path);
            free(buffer);
            return 0;
        }
        tokens[count++] = t;
    }

    if (count < 9) {
        err_msg("[Reader] Недостаточно параметров: обязательны 9 значений h w r s1 t1 s2 t2 d1 d2");
        free(buffer);
        return 0;
    }

    /* Разбираем во временную копию: при ошибке cfg остаётся нетронутым. */
    static Config tmp;
    tmp = cfg;
    double ratio;
    int d1, d2;
    if (!cfg_int(tokens[0], &tmp.h) || !cfg_int(tokens[1], &tmp.w) || !cfg_double(tokens[2], &ratio) ||
        !cfg_int(tokens[3], &tmp.move_ms[0]) || !cfg_int(tokens[4], &tmp.work_ms[0]) ||
        !cfg_int(tokens[5], &tmp.move_ms[1]) || !cfg_int(tokens[6], &tmp.work_ms[1])) {
        err_msg("[Reader] Ошибка формата обязательных числовых параметров h w r s1 t1 s2 t2");
        free(buffer);
        return 0;
    }
    if (tmp.h < 1 || tmp.h > MAX_H || tmp.w < 1 || tmp.w > MAX_W) {
        err_msg("[Reader] Размеры сада: высота 1..%d, ширина 1..%d", MAX_H, MAX_W);
        free(buffer);
        return 0;
    }
    if (!(ratio >= 0.0 && ratio <= 0.9)) {
        err_msg("[Reader] Доля препятствий r должна быть от 0 до 0.9");
        free(buffer);
        return 0;
    }
    tmp.obst_pct = (int)(ratio * 100.0 + 0.5);
    for (int g = 0; g < NG; g++) {
        if (tmp.move_ms[g] < 0 || tmp.move_ms[g] > MAX_TIME_MS || tmp.work_ms[g] < 0 || tmp.work_ms[g] > MAX_TIME_MS) {
            err_msg("[Reader] Время перехода и обработки должно быть 0..%d мс", MAX_TIME_MS);
            free(buffer);
            return 0;
        }
    }
    if (!cfg_bool(tokens[7], &d1) || !cfg_bool(tokens[8], &d2)) {
        err_msg("[Reader] Параметры d1 и d2 должны быть 0, 1, true или false");
        free(buffer);
        return 0;
    }
    tmp.bypass[0] = d1;
    tmp.bypass[1] = d2;

    /* Необязательная часть: стартовые клетки, маршрут второго садовника, препятствия. */
    size_t idx = 9;
    if (idx < count && !cfg_route(tokens[idx])) {
        if (count - idx < 4) {
            err_msg("[Reader] Стартовые позиции должны содержать четыре числа x1 y1 x2 y2");
            free(buffer);
            return 0;
        }
        if (!cfg_int(tokens[idx], &tmp.start_r[0]) || !cfg_int(tokens[idx + 1], &tmp.start_c[0]) ||
            !cfg_int(tokens[idx + 2], &tmp.start_r[1]) || !cfg_int(tokens[idx + 3], &tmp.start_c[1])) {
            err_msg("[Reader] Стартовые позиции должны быть целыми числами x1 y1 x2 y2");
            free(buffer);
            return 0;
        }
        tmp.start_set[0] = tmp.start_set[1] = 1;
        idx += 4;
    }
    if (idx < count && cfg_route(tokens[idx])) {
        tmp.corner[1] = 3;                              /* правый нижний угол */
        tmp.cols[1] = !strcmp(tokens[idx], "columns");
        idx++;
    }
    if ((count - idx) % 2U != 0U) {
        err_msg("[Reader] Координаты препятствий должны идти парами x y");
        free(buffer);
        return 0;
    }
    tmp.obst_n = 0;
    while (idx < count) {
        int r, c;
        if (tmp.obst_n >= MAX_CELLS) {
            err_msg("[Reader] Слишком много препятствий");
            free(buffer);
            return 0;
        }
        if (!cfg_int(tokens[idx], &r) || !cfg_int(tokens[idx + 1], &c) || r < 1 || c < 1) {
            err_msg("[Reader] Координаты препятствия — целые числа от 1 (строка, столбец)");
            free(buffer);
            return 0;
        }
        tmp.obst_r[tmp.obst_n] = r;
        tmp.obst_c[tmp.obst_n] = c;
        tmp.obst_n++;
        idx += 2;
    }

    cfg = tmp;
    free(buffer);
    return 1;
}
