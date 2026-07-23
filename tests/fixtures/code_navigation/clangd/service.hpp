#pragma once

class Base {
public:
    virtual int run() = 0;
    virtual ~Base() = default;
};

class Derived final : public Base {
public:
    int run() override;
};
