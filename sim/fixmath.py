C1 = -1.0 / 6.0
C2 = 1.0 / 120.0
C3 = -1.0 / 5040.0


def psin(x: float) -> float:
    x2 = x * x
    return x * (1.0 + x2 * (C1 + x2 * (C2 + x2 * C3)))
