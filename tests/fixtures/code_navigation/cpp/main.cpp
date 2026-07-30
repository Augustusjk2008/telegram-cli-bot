#include "service.hpp"

int main() {
    Greeter greeter;
    return greeter.greet("Orbit").empty();
}
