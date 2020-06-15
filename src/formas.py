
# Algunas formas de especificar una función periódica según distintos parámetros.

from math import sin, pi

def sine(every=0.1):
    # sin sapmleada a every, no tiene freq.
    t = 0.0
    while True:
        yield sin(2 * pi * t)
        t += every

s = sine()
a = [next(s) for i in range(10)]


def sine(freq=1, every=0.1):
    # es sin(freq) sampleada a every
    t = 0.0
    while True:
        yield sin(2 * pi * freq * t)
        t += every

s = sine(2)
b = [next(s) for i in range(10)]


def sine(freq=1, within=1, every=0.1):
    # señal a freq durante within.
    size = int(within / every)
    t = 0.0
    for _ in range(size):
        yield sin(2 * pi * freq * t)
        t += every

s = sine(3, 1, 0.05)  # 3 cps
c = list(s)

def sine(cycles=1, within=1, every=0.1):
    # ciclos por within
    size = int(within / every)
    step = every / within
    t = 0.0
    for _ in range(size):
        yield sin(2 * pi * cycles * t)
        t += step

s = sine(3, 2)
d = list(s)  # [next(s) for i in range(10)]
