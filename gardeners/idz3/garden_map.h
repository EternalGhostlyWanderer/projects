#ifndef GARDEN_MAP_H
#define GARDEN_MAP_H

// Печатает карту сада с садовниками (при захваченном мьютексе)
void show_map(const char *title);
// Строит сад по параметрам запуска; 0 — ошибка
int build_world(void);
// Отмечает в seen клетки, достижимые от клетки start
void flood(int start, char *seen);

#endif
