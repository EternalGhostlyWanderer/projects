#ifndef MQ_PROTO_H
#define MQ_PROTO_H

// Протокол обмена между сервером сада (garden_server) и садовниками
// (gardener_mq1, gardener_mq2) через очереди сообщений POSIX.
// Очередь запросов "<base>_q" читает сервер; ответы садовник g читает
// из очереди "<base>_a<g>".

// Запросы садовника серверу
enum {
    REQ_HELLO = 1,   // a = pid садовника; в ответ REP с параметрами и картой препятствий
    REQ_CELLINFO,    // a = клетка; ответ: a = символ препятствия (0 нет), b = состояние
    REQ_OCC,         // клетки другого садовника; ответ: a, b (-1 — нет)
    REQ_TRY,         // a = клетка, b = 1 — ожидать (учитывать в проверке тупика)
    REQ_MOVED,       // a = откуда, b = куда: прибытие и освобождение старой клетки
    REQ_BEGIN,       // a = клетка: начать обработку; ответ a = 1 — можно
    REQ_END,         // a = клетка, b = 1 — обработка завершена, 0 — прервана
    REQ_EVENT,       // data = текст события
    REQ_HALT,        // a = причина остановки (HALT_*)
    REQ_DONE         // садовник закончил: a = штатно?, b = его сигнал, c = клетка, v[] = статистика
};

#define MQ_DATA 2500

// Единый формат сообщения и запроса, и ответа
typedef struct {
    int type;        // REQ_*
    int g;           // номер садовника (с 0)
    int stop;        // в ответе: серверу нужно остановить моделирование
    int a, b, c;
    int v[12];
    char data[MQ_DATA];
} Msg;

// Индексы в v[] при передаче параметров (ответ на REQ_HELLO)
enum { V_W, V_H, V_START, V_CORNER, V_COLS, V_MOVE, V_WORK, V_BYPASS, V_VIEW, V_SRVPID };
// Индексы в v[] при передаче статистики (REQ_DONE)
enum { D_MOVES, D_WAITS, D_BYPASSES, D_SKIP_OBST, D_SKIP_DONE, D_UNREACH, D_WAIT_MS };

#endif
