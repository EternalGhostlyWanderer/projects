#include "application.h"
#include <iostream>
int main(int argc, char* argv[])
{
    Application app;
    int res = 0;
    try
    {
        app.configure();
        res = app.start(argc, argv);
    }
    catch(std::exception& e)
    {
        std::cerr << "ERROR!" << e.what();
        return -1;
    }
    catch(...)
    {
        std::cerr << "An unknown exception!";
        return -2;
    }
    return res;
}
