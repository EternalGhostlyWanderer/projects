#ifndef CONFIG_READER_H
#define CONFIG_READER_H

// Читает карту сада из файла ('#' и '~' — препятствия); 1 — успех
int load_map(const char *path);
// Читает файл конфигурации: h w r s1 t1 s2 t2 d1 d2 [x1 y1 x2 y2] [rows|columns] [x y ...]; 1 — успех
int load_config_file(const char *path);

#endif
