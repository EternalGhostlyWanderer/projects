#ifndef CMD_PARSER_H
#define CMD_PARSER_H

// Разбор командной строки (и файла -f); 0 — успех, 1 — ошибка, 2 — справка, 3 — ввод прерван
int cmd_parser_parse(int argc, char **argv);
// Значения параметров по умолчанию
void config_defaults(void);

#endif
