#ifndef SIMULATION_H
#define SIMULATION_H

// Запускает моделирование и возвращает код завершения программы
int simulation_run(void);
// Устанавливает обработчики сигналов (вызывается до диалога ввода)
void install_signal_handlers(void);

#endif
