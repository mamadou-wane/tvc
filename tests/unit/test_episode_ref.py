import ast
import importlib
import inspect
import struct
import sys
import unittest
from pathlib import Path
from typing import get_type_hints

from sim import control_ref
from sim.types import Observation


SOURCE = Path(__file__).resolve().parents[2] / "sim" / "episode.py"

# Test-owned words and numeric vocabulary, independent of episode.py.
I, A, F, T = 0, 1, 2, 3
ARM, LAUNCH, ABORT = 1, 2, 3
NONE, STABILIZED, DIVERGED, GROUND_ABORT = 0, 1, 2, 3
SENSOR_LOST, PEER_LOST, SIGNAL, NOT_SETTLED, INTERNAL = 4, 5, 6, 7, 8
QUEUED, APPLIED, APPLIED_LATE, DUPLICATE = 0, 1, 2, 3
REJECTED_PENDING, REJECTED_STATE, REJECTED_IDENTITY = 4, 5, 6
REJECTED_OPCODE, REJECTED_STALE, PREEMPTED = 7, 8, 9

z = 0x0000000000000000
nz = 0x8000000000000000
bp, bn = 0x3f947ae147ae147b, 0xbf947ae147ae147b
bop, bon = 0x3f947ae147ae147c, 0xbf947ae147ae147c
dp, dn = 0x3fd3333333333333, 0xbfd3333333333333
dop, don = 0x3fd3333333333334, 0xbfd3333333333334
w = 0x3fd8000000000000
Z = (z, z, z)
P = (0x0000000000000000, 0x3fd0000000000000, 0x3fb0000000000000)
UQ = 0x3fb079042d8c2a45
Q = (0x3f1f75104d551d69, 0x3fc0000000000000, UQ)
N = (nz, nz, 0xbfb0000000000000)
U1, U2, U3 = 0x3fa3c6a7ef9db22d, 0x3f9a5e353f7ced92, 0x3f9194237fa89e62
P1 = (z, 0x3fc0000000000000, U1)
P2 = (z, 0x3fb5555555555556, U2)
P3 = (z, 0x3fac71c71c71c71e, U3)
O3 = (0x3f80000000000000, 0xbfc0000000000000)


# These helpers only pack literal records. They contain no policy or arithmetic.
def S(mode, pid, count, pending=None, last=None, terminal=None, auto=False):
    return mode, pid, count, pending, last, terminal, auto


def X(tick, held, fresh, age, command=None, horizon=False, sim=None, stop=None):
    return tick, held, fresh, age, command, horizon, sim, stop


def H(tick, theta, omega):
    return tick, theta, omega, True


L0 = (0, LAUNCH, 5)
TP = (5, ARM, 200)
TA = (6, ABORT, 100)
H99 = H(99, z, z)
H79 = H(79, z, z)

# Each row: id, seed, inputs, next state, requested bits, ACK literals, PID calls.
# All 43 one-step expectations are explicitly expanded from the approved sheet.
VECTORS = (
    ("C01", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0, 0, 5)),
     S(I, P, 0, last=L0), z, ((0, REJECTED_OPCODE, 0, I, NONE),), 0),
    ("C02", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, L0),
     S(I, P, 0, last=L0), z, ((0, DUPLICATE, 0, I, NONE),), 0),
    ("C03", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0, ARM, 5)),
     S(I, P, 0, last=L0), z, ((0, REJECTED_IDENTITY, 0, I, NONE),), 0),
    ("C04", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0, LAUNCH, 6)),
     S(I, P, 0, last=L0), z, ((0, REJECTED_IDENTITY, 0, I, NONE),), 0),
    ("C05", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0xffffffff, ARM, 10)),
     S(I, P, 0, last=L0), z, ((0xffffffff, REJECTED_STALE, 0, I, NONE),), 0),
    ("C06", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0x80000000, ARM, 10)),
     S(I, P, 0, last=L0), z, ((0x80000000, REJECTED_STALE, 0, I, NONE),), 0),
    ("C07", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0x7fffffff, ARM, 10)),
     S(A, P, 0, last=(0x7fffffff, ARM, 10)), z, ((0x7fffffff, APPLIED, 10, A, NONE),), 0),
    ("C08", S(I, P, 0, last=(0xffffffff, LAUNCH, 5)),
     X(10, H(9, z, w), False, 1, (0, ARM, 10)),
     S(A, P, 0, last=(0, ARM, 10)), z, ((0, APPLIED, 10, A, NONE),), 0),
    ("C09", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0, 0, 5), True),
     S(T, P, 0, last=L0, terminal=(NOT_SETTLED, 10)), z,
     ((0, REJECTED_OPCODE, 0, T, NOT_SETTLED),), 0),
    ("C10", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, L0, True),
     S(T, P, 0, last=L0, terminal=(NOT_SETTLED, 10)), z,
     ((0, DUPLICATE, 0, T, NOT_SETTLED),), 0),
    ("C11", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0, ARM, 5), True),
     S(T, P, 0, last=L0, terminal=(NOT_SETTLED, 10)), z,
     ((0, REJECTED_IDENTITY, 0, T, NOT_SETTLED),), 0),
    ("C12", S(I, P, 0, last=L0), X(10, H(9, z, w), False, 1, (0xffffffff, ARM, 10), True),
     S(T, P, 0, last=L0, terminal=(NOT_SETTLED, 10)), z,
     ((0xffffffff, REJECTED_STALE, 0, T, NOT_SETTLED),), 0),
    ("T01", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 0, SIGNAL),
     S(T, P, 1000, last=TP, terminal=(INTERNAL, 100)), z,
     ((6, REJECTED_STATE, 0, T, INTERNAL), (5, REJECTED_STATE, 0, T, INTERNAL)), 0),
    ("T02", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 4, SIGNAL),
     S(T, P, 1000, last=TP, terminal=(INTERNAL, 100)), z,
     ((6, REJECTED_STATE, 0, T, INTERNAL), (5, REJECTED_STATE, 0, T, INTERNAL)), 0),
    ("T03", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 6, SIGNAL),
     S(T, P, 1000, last=TP, terminal=(INTERNAL, 100)), z,
     ((6, REJECTED_STATE, 0, T, INTERNAL), (5, REJECTED_STATE, 0, T, INTERNAL)), 0),
    ("T04", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 0xffffffff, SIGNAL),
     S(T, P, 1000, last=TP, terminal=(INTERNAL, 100)), z,
     ((6, REJECTED_STATE, 0, T, INTERNAL), (5, REJECTED_STATE, 0, T, INTERNAL)), 0),
    ("T05", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 2, SIGNAL),
     S(T, P, 1000, last=TP, terminal=(SIGNAL, 100)), z,
     ((6, REJECTED_STATE, 0, T, SIGNAL), (5, REJECTED_STATE, 0, T, SIGNAL)), 0),
    ("T06", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 3, PEER_LOST),
     S(T, P, 1000, last=TP, terminal=(PEER_LOST, 100)), z,
     ((6, REJECTED_STATE, 0, T, PEER_LOST), (5, REJECTED_STATE, 0, T, PEER_LOST)), 0),
    ("T07", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, True, 1, INTERNAL),
     S(T, P, 1000, last=TP, terminal=(INTERNAL, 100)), z,
     ((6, REJECTED_STATE, 0, T, INTERNAL), (5, REJECTED_STATE, 0, T, INTERNAL)), 0),
    ("T08", S(F, P, 999, TP, TP), X(100, H79, False, 21, TA, True, 2),
     S(T, P, 1000, last=TP, terminal=(DIVERGED, 100)), z,
     ((6, REJECTED_STATE, 0, T, DIVERGED), (5, REJECTED_STATE, 0, T, DIVERGED)), 0),
    ("T09", S(F, P, 999, TP, TP), X(100, None, False, 1, TA, True, 3),
     S(T, P, 0, last=TP, terminal=(DIVERGED, 100)), z,
     ((6, REJECTED_STATE, 0, T, DIVERGED), (5, REJECTED_STATE, 0, T, DIVERGED)), 0),
    ("T10", S(F, P, 999, TP, TP), X(100, H(79, dop, z), True, 21, TA, True),
     S(T, P, 0, last=TP, terminal=(DIVERGED, 100)), z,
     ((6, REJECTED_STATE, 0, T, DIVERGED), (5, REJECTED_STATE, 0, T, DIVERGED)), 0),
    ("T11", S(F, P, 999, TP, TP), X(100, H(79, don, z), True, 21, TA, True),
     S(T, P, 0, last=TP, terminal=(DIVERGED, 100)), z,
     ((6, REJECTED_STATE, 0, T, DIVERGED), (5, REJECTED_STATE, 0, T, DIVERGED)), 0),
    ("T12", S(F, P, 999, TP, TP), X(100, H(79, *O3), True, 21, TA, True),
     S(T, P, 0, last=TP, terminal=(SENSOR_LOST, 100)), z,
     ((6, REJECTED_STATE, 0, T, SENSOR_LOST), (5, REJECTED_STATE, 0, T, SENSOR_LOST)), 0),
    ("T13", S(F, P, 999, TP, TP), X(100, H99, False, 1, TP, True),
     S(T, P, 1000, last=TP, terminal=(STABILIZED, 100)), z,
     ((5, DUPLICATE, 0, T, STABILIZED), (5, REJECTED_STATE, 0, T, STABILIZED)), 0),
    ("T14", S(F, P, 999, TP, TP), X(100, H99, False, 1, TA, False, 1),
     S(T, P, 1000, last=TP, terminal=(STABILIZED, 100)), z,
     ((6, REJECTED_STATE, 0, T, STABILIZED), (5, REJECTED_STATE, 0, T, STABILIZED)), 0),
    ("T15", S(F, P, 998, TP, TP), X(100, H99, False, 1, TA, True),
     S(T, P, 999, last=TP, terminal=(NOT_SETTLED, 100)), z,
     ((6, REJECTED_STATE, 0, T, NOT_SETTLED), (5, REJECTED_STATE, 0, T, NOT_SETTLED)), 0),
    ("T16", S(F, P, 999, TP, TP), X(100, H79, False, 21, TA, True),
     S(T, P, 1000, last=TP, terminal=(SENSOR_LOST, 100)), z,
     ((6, REJECTED_STATE, 0, T, SENSOR_LOST), (5, REJECTED_STATE, 0, T, SENSOR_LOST)), 0),
    ("B01", S(A, P, 998, (30, LAUNCH, 100), (30, LAUNCH, 100)),
     X(40, H(40, z, z), True, 0, (31, ABORT, 40)),
     S(T, P, 999, last=(31, ABORT, 40), terminal=(GROUND_ABORT, 40)), z,
     ((31, APPLIED, 40, T, GROUND_ABORT), (30, PREEMPTED, 0, A, NONE)), 0),
    ("B02", S(I, P, 0, (30, ARM, 100), (30, ARM, 100)),
     X(40, H(40, *O3), True, 0, (31, ABORT, 40)),
     S(I, P, 0, last=(31, ABORT, 40)), z,
     ((31, REJECTED_STATE, 0, I, NONE), (30, PREEMPTED, 0, I, NONE)), 0),
    ("B03", S(I, P, 0), X(40, H(39, z, w), False, 1, (30, LAUNCH, 40)),
     S(I, P, 0, last=(30, LAUNCH, 40)), z, ((30, REJECTED_STATE, 0, I, NONE),), 0),
    ("B04", S(I, P, 0, (30, ARM, 39), (30, ARM, 39)), X(40, H(39, z, w), False, 1),
     S(A, P, 0, last=(30, ARM, 39)), z, ((30, APPLIED_LATE, 40, A, NONE),), 0),
    ("B05", S(F, P, 0), X(100, H(80, *O3), True, 20), S(F, Q, 0), UQ, (), 1),
    ("B06", S(I, P, 0), X(40, H(40, dp, z), True, 0), S(I, P, 0), z, (), 0),
    ("B07", S(I, P, 0), X(40, H(40, dn, z), True, 0), S(I, P, 0), z, (), 0),
    ("B08", S(F, N, 998), X(100, H(92, z, z), False, 8),
     S(F, N, 999), 0xbfb0000000000000, (), 0),
    ("B09", S(F, N, 998), X(100, H(91, z, z), False, 9), S(F, N, 999), z, (), 0),
    ("B10", S(I, P, 998), X(20, None, False, 21),
     S(T, P, 0, terminal=(SENSOR_LOST, 20)), z, (), 0),
    ("B11", S(A, P, 998), X(100, H79, True, 21),
     S(T, P, 999, terminal=(SENSOR_LOST, 100)), z, (), 0),
    ("B12", S(I, P, 998), X(100, H(92, z, bon), False, 8), S(I, P, 0), z, (), 0),
    ("B13", S(I, Z, 0, auto=True), X(0, H(0, z, z), True, 0),
     S(F, Z, 1, auto=True), z, (), 1),
    ("B14", S(I, P1, 998, auto=True), X(50, H(50, z, z), True, 0, (40, ARM, 50)),
     S(F, P2, 999, last=(40, ARM, 50), auto=True), U2, ((40, APPLIED, 50, A, NONE),), 1),
    ("B15", S(A, P1, 998), X(50, H(50, z, z), True, 0, (40, LAUNCH, 50)),
     S(F, P2, 999, last=(40, LAUNCH, 50)), U2, ((40, APPLIED, 50, F, NONE),), 1),
)

q10, q11, q12 = (10, ARM, 12), (11, LAUNCH, 12), (12, ARM, 16)
r20, r21 = (20, LAUNCH, 35), (21, ABORT, 34)

# Each trace step: inputs, full next state, request bits, ACKs, real PID calls.
# Repetitive ladder ticks are spelled out; no expected recurrence is run here.
TRACES = (
    ("L", S(I, P, 0), (
        (X(0, None, False, 1, (1, ARM, 0)), S(A, P, 0, last=(1, ARM, 0)), z,
         ((1, APPLIED, 0, A, NONE),), 0),
        (X(1, None, False, 2, (1, ARM, 0)), S(A, P, 0, last=(1, ARM, 0)), z,
         ((1, DUPLICATE, 0, A, NONE),), 0),
        (X(2, None, False, 3, (2, ARM, 2)), S(A, P, 0, last=(2, ARM, 2)), z,
         ((2, REJECTED_STATE, 0, A, NONE),), 0),
        (X(3, None, False, 4, (3, LAUNCH, 3)), S(F, P, 0, last=(3, LAUNCH, 3)),
         0x3fb0000000000000, ((3, APPLIED, 3, F, NONE),), 0),
        (X(4, None, False, 5, (4, LAUNCH, 4)), S(F, P, 0, last=(4, LAUNCH, 4)),
         0x3fb0000000000000, ((4, REJECTED_STATE, 0, F, NONE),), 0),
        (X(5, None, False, 6, (5, ARM, 5)), S(F, P, 0, last=(5, ARM, 5)),
         0x3fb0000000000000, ((5, REJECTED_STATE, 0, F, NONE),), 0),
        (X(6, None, False, 7, (6, ABORT, 6)),
         S(T, P, 0, last=(6, ABORT, 6), terminal=(GROUND_ABORT, 6)), z,
         ((6, APPLIED, 6, T, GROUND_ABORT),), 0),
        (X(7, H(7, z, z), True, 0, (7, ARM, 7), True, 0, SIGNAL),
         S(T, P, 0, last=(6, ABORT, 6), terminal=(GROUND_ABORT, 6)), z, (), 0),
    )),
    ("Q", S(I, P, 0), (
        (X(10, H(9, z, w), False, 1, q10), S(I, P, 0, q10, q10), z,
         ((10, QUEUED, 0, I, NONE),), 0),
        (X(11, H(9, z, w), False, 2, (11, LAUNCH, 13)), S(I, P, 0, q10, q10), z,
         ((11, REJECTED_PENDING, 0, I, NONE),), 0),
        (X(12, H(9, z, w), False, 3, q10), S(A, P, 0, last=q10), z,
         ((10, DUPLICATE, 0, I, NONE), (10, APPLIED, 12, A, NONE)), 0),
        (X(13, H(13, *O3), True, 0, q11), S(F, Q, 0, last=q11), UQ,
         ((11, APPLIED_LATE, 13, F, NONE),), 1),
        (X(14, H(13, *O3), False, 1, q12), S(F, Q, 0, q12, q12), UQ,
         ((12, QUEUED, 0, F, NONE),), 0),
        (X(15, H(13, *O3), False, 2), S(F, Q, 0, q12, q12), UQ, (), 0),
        (X(16, H(13, *O3), False, 3), S(F, Q, 0, last=q12), UQ,
         ((12, REJECTED_STATE, 0, F, NONE),), 0),
        (X(17, H(13, *O3), False, 4, q12), S(F, Q, 0, last=q12), UQ,
         ((12, DUPLICATE, 0, F, NONE),), 0),
    )),
    ("R", S(A, P, 0), (
        (X(30, H(29, z, w), False, 1, r20), S(A, P, 0, r20, r20), z,
         ((20, QUEUED, 0, A, NONE),), 0),
        (X(31, H(29, z, w), False, 2, r21), S(A, P, 0, r21, r21), z,
         ((21, QUEUED, 0, A, NONE), (20, PREEMPTED, 0, A, NONE)), 0),
        (X(32, H(29, z, w), False, 3, (22, ARM, 32)), S(A, P, 0, r21, r21), z,
         ((22, REJECTED_PENDING, 0, A, NONE),), 0),
        (X(33, H(29, z, w), False, 4, (22, ABORT, 33)), S(A, P, 0, r21, r21), z,
         ((22, REJECTED_PENDING, 0, A, NONE),), 0),
        (X(34, H(29, z, w), False, 5, r21),
         S(T, P, 0, last=r21, terminal=(GROUND_ABORT, 34)), z,
         ((21, DUPLICATE, 0, A, NONE), (21, APPLIED, 34, T, GROUND_ABORT)), 0),
    )),
    ("K", S(F, Z, 0), (
        (X(0, H(0, z, w), True, 0), S(F, P1, 0), U1, (), 1),
        (X(1, H(0, z, w), False, 1), S(F, P1, 0), U1, (), 0),
        (X(2, H(0, z, w), False, 2), S(F, P1, 0), U1, (), 0),
        (X(3, H(0, z, w), False, 3), S(F, P1, 0), U1, (), 0),
        (X(4, H(0, z, w), False, 4), S(F, P1, 0), U1, (), 0),
        (X(5, H(0, z, w), False, 5), S(F, P1, 0), U1, (), 0),
        (X(6, H(0, z, w), False, 6), S(F, P1, 0), U1, (), 0),
        (X(7, H(0, z, w), False, 7), S(F, P1, 0), U1, (), 0),
        (X(8, H(0, z, w), False, 8), S(F, P1, 0), U1, (), 0),
        (X(9, H(9, z, z), True, 0), S(F, P2, 1), U2, (), 1),
        (X(10, H(9, z, z), False, 1), S(F, P2, 2), U2, (), 0),
        (X(11, H(9, z, z), False, 2), S(F, P2, 3), U2, (), 0),
        (X(12, H(9, z, z), False, 3), S(F, P2, 4), U2, (), 0),
        (X(13, H(9, z, z), False, 4), S(F, P2, 5), U2, (), 0),
        (X(14, H(9, z, z), False, 5), S(F, P2, 6), U2, (), 0),
        (X(15, H(9, z, z), False, 6), S(F, P2, 7), U2, (), 0),
        (X(16, H(9, z, z), False, 7), S(F, P2, 8), U2, (), 0),
        (X(17, H(9, z, z), False, 8), S(F, P2, 9), U2, (), 0),
        (X(18, H(9, z, z), False, 9), S(F, P2, 10), z, (), 0),
        (X(19, H(9, z, z), False, 10), S(F, P2, 11), z, (), 0),
        (X(20, H(9, z, z), False, 11), S(F, P2, 12), z, (), 0),
        (X(21, H(9, z, z), False, 12), S(F, P2, 13), z, (), 0),
        (X(22, H(9, z, z), False, 13), S(F, P2, 14), z, (), 0),
        (X(23, H(9, z, z), False, 14), S(F, P2, 15), z, (), 0),
        (X(24, H(9, z, z), False, 15), S(F, P2, 16), z, (), 0),
        (X(25, H(9, z, z), False, 16), S(F, P2, 17), z, (), 0),
        (X(26, H(9, z, z), False, 17), S(F, P2, 18), z, (), 0),
        (X(27, H(9, z, z), False, 18), S(F, P2, 19), z, (), 0),
        (X(28, H(9, z, z), False, 19), S(F, P2, 20), z, (), 0),
        (X(29, H(9, z, z), False, 20), S(F, P2, 21), z, (), 0),
        (X(30, H(30, z, z), True, 0), S(F, P3, 22), U3, (), 1),
    )),
    ("S", S(I, P, 998), (
        (X(0, H(0, bp, bn), True, 0), S(I, P, 999), z, (), 0),
        (X(1, H(0, bp, bn), False, 1), S(I, P, 1000), z, (), 0),
        (X(2, H(2, bn, bp), True, 0), S(I, P, 1000), z, (), 0),
        (X(3, H(3, bop, z), True, 0), S(I, P, 0), z, (), 0),
        (X(4, H(4, bon, z), True, 0), S(I, P, 0), z, (), 0),
        (X(5, H(4, bon, z), False, 1), S(I, P, 0), z, (), 0),
        (X(6, H(6, z, bop), True, 0), S(I, P, 0), z, (), 0),
        (X(7, H(7, z, bon), True, 0), S(I, P, 0), z, (), 0),
        (X(8, H(8, z, z), True, 0), S(I, P, 1), z, (), 0),
        (X(9, H(8, z, z), False, 1, horizon=True),
         S(T, P, 2, terminal=(NOT_SETTLED, 9)), z, (), 0),
    )),
    ("A", S(I, P, 0, auto=True), (
        (X(0, None, False, 1), S(I, P, 0, auto=True), z, (), 0),
        (X(1, None, False, 2, (1, ARM, 1)), S(A, P, 0, last=(1, ARM, 1), auto=True),
         z, ((1, APPLIED, 1, A, NONE),), 0),
        (X(2, H(2, *O3), True, 0), S(F, Q, 0, last=(1, ARM, 1), auto=True), UQ, (), 1),
    )),
)


def from_bits(word):
    return struct.unpack("<d", struct.pack("<Q", word))[0]


def bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def state_words(state):
    return (state.mode, tuple(bits(v) for v in state.pid), state.settle_count,
            state.pending, state.last_accepted, state.terminal, state.auto_arm)


def input_words(inputs):
    held = inputs.held
    observation = None if held is None else (held.tick, bits(held.theta), bits(held.omega), held.valid)
    return (inputs.tick, observation, inputs.fresh, inputs.staleness, inputs.command,
            inputs.horizon_reached, inputs.sim_reason, inputs.stop_reason)


def with_pid_counts(function, *args, **kwargs):
    # Observe the real code objects without replacing functions or their outputs.
    # This also counts a directly imported alias of the frozen PID function.
    counts = {"step": 0, "initial": 0}
    names = {control_ref.step.__code__: "step", control_ref.initial.__code__: "initial"}
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if event == "call" and frame.f_code in names:
            counts[names[frame.f_code]] += 1
        if previous is not None:
            previous(frame, event, arg)

    try:
        sys.setprofile(observe)
        result = function(*args, **kwargs)
    finally:
        sys.setprofile(previous)
    return result, counts


class OracleInventoryTests(unittest.TestCase):
    def test_all_approved_rows_are_present_once(self):
        self.assertEqual([row[0] for row in VECTORS],
                         [f"C{n:02}" for n in range(1, 13)]
                         + [f"T{n:02}" for n in range(1, 17)]
                         + [f"B{n:02}" for n in range(1, 16)])
        self.assertEqual([(name, len(rows)) for name, _, rows in TRACES],
                         [("L", 8), ("Q", 8), ("R", 5), ("K", 31), ("S", 10), ("A", 3)])
        self.assertEqual(len(VECTORS) + sum(len(rows) for _, _, rows in TRACES), 108)
        self.assertEqual(sum(row[-1] for row in VECTORS), 4)
        self.assertEqual(sum(row[-1] for _, _, rows in TRACES for row in rows), 5)


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.ep = importlib.import_module("sim.episode")

    def make_command(self, value):
        return None if value is None else self.ep.Command(*value)

    def make_state(self, value):
        mode, pid, count, pending, last, terminal, auto = value
        result = self.ep.EpisodeState(
            self.ep.Mode(mode), control_ref.ControlState(*(from_bits(v) for v in pid)), count,
            self.make_command(pending), self.make_command(last),
            None if terminal is None else self.ep.TerminalResult(self.ep.Reason(terminal[0]), terminal[1]),
            auto,
        )
        self.assertEqual(state_words(result), value)
        return result

    def make_input(self, value):
        tick, held, fresh, age, command, horizon, sim, stop = value
        observation = None if held is None else Observation(
            held[0], from_bits(held[1]), from_bits(held[2]), held[3])
        result = self.ep.EpisodeInput(tick, observation, fresh, age, self.make_command(command),
                                      horizon, sim, None if stop is None else self.ep.Reason(stop))
        self.assertEqual(input_words(result), value)
        return result

    def check_step(self, state, row):
        inputs, expected_state, delta, acks, calls = row
        inputs = self.make_input(inputs)
        before_state, before_input = state_words(state), input_words(inputs)
        result, counts = with_pid_counts(self.ep.step, state, inputs)
        self.assertEqual(counts, {"step": calls, "initial": 0})
        self.assertIs(type(result), self.ep.EpisodeOutput)
        self.assertIs(type(result.state), self.ep.EpisodeState)
        self.assertIs(type(result.state.mode), self.ep.Mode)
        self.assertIs(type(result.state.pid), control_ref.ControlState)
        self.assertIs(type(result.requested_delta), float)
        self.assertIs(type(result.acks), tuple)
        self.assertLessEqual(len(result.acks), 2)
        for ack in result.acks:
            self.assertIs(type(ack), self.ep.Ack)
            self.assertIs(type(ack.status), self.ep.AckStatus)
            self.assertIs(type(ack.state), self.ep.Mode)
            self.assertIs(type(ack.reason), self.ep.Reason)
        if result.state.terminal is not None:
            self.assertIs(type(result.state.terminal), self.ep.TerminalResult)
            self.assertIs(type(result.state.terminal.reason), self.ep.Reason)
        self.assertEqual(state_words(result.state), expected_state)
        self.assertEqual(bits(result.requested_delta), delta)
        self.assertEqual(result.acks, acks)
        self.assertEqual(state_words(state), before_state)
        self.assertEqual(input_words(inputs), before_input)
        return result.state

    def check_vectors(self, prefix):
        for name, seed, *row in VECTORS:
            if name.startswith(prefix):
                with self.subTest(vector=name):
                    self.check_step(self.make_state(seed), row)

    def check_trace(self, name):
        _, seed, rows = next(trace for trace in TRACES if trace[0] == name)
        state = self.make_state(seed)
        for number, row in enumerate(rows):
            with self.subTest(trace=name, step=number, tick=row[0][0]):
                state = self.check_step(state, row)

    def test_identity_prefix_and_modular_boundaries(self):
        self.check_vectors("C")

    def test_terminal_precedence_and_complete_ack_batch(self):
        self.check_vectors("T")

    def test_application_age_and_counter_boundaries(self):
        self.check_vectors("B")

    def test_trace_L_manual_lifecycle_and_absorption(self):
        self.check_trace("L")

    def test_trace_Q_arrival_before_due_and_late_application(self):
        self.check_trace("Q")

    def test_trace_R_preemption_pending_protection_and_terminal_acks(self):
        self.check_trace("R")

    def test_trace_K_coast_neutral_and_real_pid_recovery(self):
        self.check_trace("K")

    def test_trace_S_held_settling_equality_cap_reset_and_horizon(self):
        self.check_trace("S")

    def test_trace_A_promotion_waits_for_freshness_without_pid_reset(self):
        self.check_trace("A")

    def test_initialization_cases_call_frozen_pid_once(self):
        for auto in (False, True):
            with self.subTest(auto_arm=auto):
                state, counts = with_pid_counts(self.ep.initial, auto_arm=auto)
                self.assertEqual(counts, {"step": 0, "initial": 1})
                self.assertIs(type(state), self.ep.EpisodeState)
                self.assertEqual(state_words(state), S(I, Z, 0, auto=auto))

    def test_enum_numeric_vocabulary_is_exact(self):
        enums = {
            "Mode": {"INIT": 0, "ARMED": 1, "FLYING": 2, "TERMINATED": 3},
            "Reason": {"NONE": 0, "STABILIZED": 1, "DIVERGED": 2, "GROUND_ABORT": 3,
                       "SENSOR_LOST": 4, "PEER_LOST": 5, "SIGNAL": 6, "NOT_SETTLED": 7, "INTERNAL": 8},
            "Opcode": {"ARM": 1, "LAUNCH": 2, "ABORT": 3},
            "AckStatus": {"QUEUED": 0, "APPLIED": 1, "APPLIED_LATE": 2, "DUPLICATE": 3,
                          "REJECTED_PENDING": 4, "REJECTED_STATE": 5, "REJECTED_IDENTITY": 6,
                          "REJECTED_OPCODE": 7, "REJECTED_STALE": 8, "PREEMPTED": 9,
                          "REJECTED_OVERFLOW": 10},
            "SimReason": {"SIM_NONE": 0, "SIM_HORIZON": 1, "SIM_LOC_ANGLE": 2,
                          "SIM_LOC_NONFINITE": 3, "SIM_VEHICLE_TERMINAL": 4, "SIM_PEER_LOST": 6},
        }
        for name, expected in enums.items():
            with self.subTest(enum=name):
                self.assertEqual({key: member.value for key, member in getattr(self.ep, name).__members__.items()},
                                 expected)

    def test_record_field_order_and_types_are_exact(self):
        ep = self.ep
        contracts = {
            "Command": (("cmd_seq", "opcode", "effective_tick"), (int, int, int)),
            "Ack": (("cmd_seq", "status", "applied_tick", "state", "reason"),
                    (int, ep.AckStatus, int, ep.Mode, ep.Reason)),
            "TerminalResult": (("reason", "tick"), (ep.Reason, int)),
            "EpisodeState": (("mode", "pid", "settle_count", "pending", "last_accepted", "terminal", "auto_arm"),
                             (ep.Mode, control_ref.ControlState, int, ep.Command | None,
                              ep.Command | None, ep.TerminalResult | None, bool)),
            "EpisodeInput": (("tick", "held", "fresh", "staleness", "command", "horizon_reached", "sim_reason", "stop_reason"),
                             (int, Observation | None, bool, int, ep.Command | None, bool, int | None, ep.Reason | None)),
            "EpisodeOutput": (("state", "requested_delta", "acks"),
                              (ep.EpisodeState, float, tuple[ep.Ack, ...])),
        }
        for name, (fields, annotations) in contracts.items():
            record = getattr(ep, name)
            with self.subTest(record=name):
                self.assertTrue(issubclass(record, tuple))
                self.assertEqual(record._fields, fields)
                self.assertEqual(tuple(get_type_hints(record).values()), annotations)

    def test_records_and_nested_results_are_immutable(self):
        ep = self.ep
        state = self.make_state(S(I, N, 998, last=L0))
        ack = ep.Ack(1, ep.AckStatus.QUEUED, 0, ep.Mode.INIT, ep.Reason.NONE)
        values = (ep.Command(*L0), ack, ep.TerminalResult(ep.Reason.SIGNAL, 2), state,
                  self.make_input(X(1, H(0, nz, z), False, 1)),
                  ep.EpisodeOutput(state, from_bits(nz), (ack,)))
        for value in values:
            with self.subTest(record=type(value).__name__):
                with self.assertRaises(AttributeError):
                    setattr(value, value._fields[0], None)

    def test_constructors_preserve_finite_float_representations(self):
        state = self.make_state(S(F, N, 998))
        inputs = self.make_input(X(100, H(92, nz, bp), False, 8))
        result = self.ep.EpisodeOutput(state, from_bits(nz), ())
        self.assertEqual(tuple(bits(v) for v in result.state.pid), N)
        self.assertEqual(bits(inputs.held.theta), nz)
        self.assertEqual(bits(inputs.held.omega), bp)
        self.assertEqual(bits(result.requested_delta), nz)

    def test_public_function_signatures_are_exact(self):
        initial = inspect.signature(self.ep.initial)
        self.assertEqual(tuple(initial.parameters), ("auto_arm",))
        self.assertIs(initial.parameters["auto_arm"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(initial.parameters["auto_arm"].default, inspect.Parameter.empty)
        self.assertEqual(get_type_hints(self.ep.initial), {"auto_arm": bool, "return": self.ep.EpisodeState})
        self.assertEqual(tuple(inspect.signature(self.ep.step).parameters), ("state", "inputs"))
        self.assertEqual(get_type_hints(self.ep.step),
                         {"state": self.ep.EpisodeState, "inputs": self.ep.EpisodeInput,
                          "return": self.ep.EpisodeOutput})

    def test_runtime_imports_preserve_the_episode_layer(self):
        tree = ast.parse(SOURCE.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = ("sim." if node.level else "") + (node.module or "")
                module = module.rstrip(".")
                if module == "sim":
                    imports.extend("sim." + alias.name for alias in node.names)
                else:
                    imports.append(module)
        forbidden = {"socket", "ssl", "http", "urllib", "time", "datetime", "threading",
                     "multiprocessing", "subprocess", "concurrent", "asyncio", "selectors",
                     "os", "pathlib", "shutil", "tempfile", "glob", "random", "importlib"}
        for name in imports:
            with self.subTest(dependency=name):
                if name.startswith("sim."):
                    self.assertIn(name, {"sim.control_ref", "sim.types"})
                else:
                    root = name.split(".", 1)[0]
                    self.assertIn(root, sys.stdlib_module_names)
                    self.assertNotIn(root, forbidden)

    def test_no_dynamic_import_or_io_execution_escape(self):
        tree = ast.parse(SOURCE.read_text())
        forbidden = {"open", "__import__", "eval", "exec", "compile", "input", "print"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden)
                elif isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, forbidden | {"read_text", "write_text", "read_bytes", "write_bytes"})


if __name__ == "__main__":
    unittest.main()
