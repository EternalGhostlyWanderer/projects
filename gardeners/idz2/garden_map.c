#define _GNU_SOURCE
#include "simulation_internal.h"
#include "garden_map.h"

static const int DR_MAP[4] = {-1, 1, 0, 0};
static const int DC_MAP[4] = {0, 0, -1, 1};

void show_map(const char *title)
{
    char buf[MAX_H * (MAX_W * 2 + 8) + 256];
    int n = 0, done = 0;
    for (int c = 0; c < NC; c++)
        if (!obst[c] && cell_state[c] == CS_DONE) done++;
    n += snprintf(buf + n, sizeof buf - (size_t)n,
                  "    -- %s (обработано %d из %d) --\n", title, done, NFREE);
    for (int r = 0; r < H; r++) {
        n += snprintf(buf + n, sizeof buf - (size_t)n, "    ");
        for (int c = 0; c < W; c++) {
            int i = r * W + c;
            char ch;
            if (gd[0].pos == i) ch = '1';
            else if (gd[1].pos == i) ch = '2';
            else if (obst[i]) ch = obst[i];
            else if (cell_state[i] == CS_DONE) ch = '+';
            else ch = '.';
            buf[n++] = ch;
            buf[n++] = ' ';
        }
        buf[n++] = '\n';
    }
    out_raw(buf, (size_t)n);
}

const char *corner_name[4] = {"левый верхний", "правый верхний",
                                     "левый нижний", "правый нижний"};

/* Маршрут-змейка из угла corner: по строкам (cols=0) или столбцам (cols=1). */
static void gen_route(int g, int corner, int cols)
{
    int right = corner & 1, bottom = corner >> 1, n = 0;
    int outer = cols ? W : H, inner = cols ? H : W;
    for (int i = 0; i < outer; i++) {
        for (int k = 0; k < inner; k++) {
            int kk = (i % 2 == 0) ? k : inner - 1 - k; /* змейка */
            int r, c;
            if (!cols) {
                r = bottom ? H - 1 - i : i;
                c = right ? W - 1 - kk : kk;
            } else {
                c = right ? W - 1 - i : i;
                r = bottom ? H - 1 - kk : kk;
            }
            route[g][n++] = r * W + c;
        }
    }
}

int build_world(void)
{
    memset(obst, 0, sizeof obst);
    if (cfg.map_file) {
        if (!load_map(cfg.map_file)) return 0;
    } else {
        W = cfg.w;
        H = cfg.h;
    }
    NC = W * H;
    for (int g = 0; g < NG; g++) {
        gen_route(g, cfg.corner[g], cfg.cols[g]);
        if (cfg.start_set[g]) {
            int r = cfg.start_r[g], c = cfg.start_c[g];
            if (r < 1 || r > H || c < 1 || c > W) {
                err_msg("Стартовая клетка садовника %d (%d,%d) вне сада %dx%d", g + 1,
                        r, c, H, W);
                return 0;
            }
            start_cell[g] = (r - 1) * W + (c - 1);
        } else {
            start_cell[g] = route[g][0];
        }
    }
    if (start_cell[0] == start_cell[1]) {
        err_msg("Стартовые клетки садовников совпадают — они не могут стоять вместе");
        return 0;
    }
    if (!cfg.map_file) { /* случайные препятствия, старты всегда свободны */
        unsigned seed = cfg.seed;
        for (int c = 0; c < NC; c++) {
            if (c == start_cell[0] || c == start_cell[1]) continue;
            if ((int)(rand_r(&seed) % 100) < cfg.obst_pct)
                obst[c] = (rand_r(&seed) % 100 < 60) ? '#' : '~';
        }
    }
    /* Препятствия, явно заданные в файле конфигурации (поверх случайных или из карты). */
    for (int i = 0; i < cfg.obst_n; i++) {
        int r = cfg.obst_r[i], c = cfg.obst_c[i];
        if (r < 1 || r > H || c < 1 || c > W) {
            err_msg("Препятствие (%d,%d) вне сада %dx%d", r, c, H, W);
            return 0;
        }
        obst[(r - 1) * W + (c - 1)] = '#';
    }
    for (int g = 0; g < NG; g++) {
        if (obst[start_cell[g]]) {
            err_msg("Стартовая клетка садовника %d (%d,%d) недоступна", g + 1,
                    ROW(start_cell[g]), COL(start_cell[g]));
            return 0;
        }
    }
    NFREE = 0;
    for (int c = 0; c < NC; c++) {
        owner[c] = -1;
        cell_state[c] = obst[c] ? CS_OBST : CS_TODO;
        completed_once[c] = 0;
        if (!obst[c]) NFREE++;
    }
    for (int g = 0; g < NG; g++) waiting_for[g] = -1;
    return 1;
}

/* Заливка достижимых клеток от start (для диагностики). */
void flood(int start, char *seen)
{
    int q[MAX_CELLS], head = 0, tail = 0;
    seen[start] = 1;
    q[tail++] = start;
    while (head < tail) {
        int c = q[head++];
        for (int d = 0; d < 4; d++) {
            int nr = c / W + DR_MAP[d], nc = c % W + DC_MAP[d];
            if (nr < 0 || nr >= H || nc < 0 || nc >= W) continue;
            int n = nr * W + nc;
            if (seen[n] || obst[n]) continue;
            seen[n] = 1;
            q[tail++] = n;
        }
    }
}
