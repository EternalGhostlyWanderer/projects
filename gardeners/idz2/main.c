#include "cmd_parser.h"
#include "simulation.h"

int main(int argc, char **argv)
{
    config_defaults();
    install_signal_handlers(); /* сигналы действуют уже во время диалога ввода */

    int result = cmd_parser_parse(argc, argv);
    if (result == 2) {
        return 0; /* Запрошена справка. */
    }
    if (result != 0) {
        return result;
    }

    return simulation_run();
}
