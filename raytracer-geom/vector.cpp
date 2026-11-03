#include "vector.h"

Vector::Vector() : data_() {
}

Vector::Vector(double x, double y, double z) {
    data_[0] = x;
    data_[1] = y;
    data_[2] = z;
}

void Vector::Normalize() {
    double len = std::sqrt(data_[0] * data_[0] + data_[1] * data_[1] + data_[2] * data_[2]);
    if (len != 0) {
        data_[0] /= len;
        data_[1] /= len;
        data_[2] /= len;
    }
}

Vector& Vector::operator+=(const Vector& other) {
    data_[0] += other.data_[0];
    data_[1] += other.data_[1];
    data_[2] += other.data_[2];
    return *this;
}

Vector& Vector::operator-=(const Vector& other) {
    data_[0] -= other.data_[0];
    data_[1] -= other.data_[1];
    data_[2] -= other.data_[2];
    return *this;
}

Vector& Vector::operator*=(double scalar) {
    data_[0] *= scalar;
    data_[1] *= scalar;
    data_[2] *= scalar;
    return *this;
}

Vector& Vector::operator*=(const Vector& other) {
    data_[0] *= other.data_[0];
    data_[1] *= other.data_[1];
    data_[2] *= other.data_[2];
    return *this;
}

Vector& Vector::operator/=(double scalar) {
    data_[0] /= scalar;
    data_[1] /= scalar;
    data_[2] /= scalar;
    return *this;
}

Vector operator+(Vector lhs, const Vector& rhs) {
    lhs += rhs;
    return lhs;
}

Vector operator-(Vector lhs, const Vector& rhs) {
    lhs -= rhs;
    return lhs;
}

Vector operator*(Vector lhs, double scalar) {
    lhs *= scalar;
    return lhs;
}

Vector operator*(double scalar, Vector rhs) {
    rhs *= scalar;
    return rhs;
}

Vector operator*(const Vector& lhs, const Vector& rhs) {
    return Vector(lhs[0] * rhs[0], lhs[1] * rhs[1], lhs[2] * rhs[2]);
}

Vector operator/(Vector lhs, double scalar) {
    lhs /= scalar;
    return lhs;
}

double DotProduct(const Vector& a, const Vector& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

Vector CrossProduct(const Vector& a, const Vector& b) {
    return Vector(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]);
}

double Length(const Vector& v) {
    return std::sqrt(DotProduct(v, v));
}
