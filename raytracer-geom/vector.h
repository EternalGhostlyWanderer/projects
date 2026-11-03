#pragma once

#include <array>
#include <cstddef>
#include <cmath>

class Vector {
public:
    Vector();
    Vector(double x, double y, double z);

    double& operator[](size_t ind) {
        return data_[ind];
    }
    double operator[](size_t ind) const {
        return data_[ind];
    }

    void Normalize();

    Vector& operator+=(const Vector& other);
    Vector& operator-=(const Vector& other);
    Vector& operator*=(double scalar);
    Vector& operator*=(const Vector& other);
    Vector& operator/=(double scalar);

private:
    std::array<double, 3> data_;
};

Vector operator+(Vector lhs, const Vector& rhs);
Vector operator-(Vector lhs, const Vector& rhs);
Vector operator*(Vector lhs, double scalar);
Vector operator*(double scalar, Vector rhs);
Vector operator*(const Vector& lhs, const Vector& rhs);
Vector operator/(Vector lhs, double scalar);

double DotProduct(const Vector& a, const Vector& b);
Vector CrossProduct(const Vector& a, const Vector& b);
double Length(const Vector& v);
