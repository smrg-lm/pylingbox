
# ------------------------------------------------------------------------------
# Para triggers:

def within(time, seq):
    delta = time / len(seq)
    unit = time
    for value in seq:
        yield (unit, delta, value)

def every(time, seq):
    delta = time
    unit = time * len(seq)
    for value in seq:
        yield (unit, delta, value)

# within comprime o expande temporalmente la salida de every.
def within2(time, seq):  # n every d within t  (cambia la proporción, nada más, pero no era eso lo que pensé primero).
    new_unit = time
    for i in seq:
        old_unit = i[0]
        scale = new_unit / old_unit
        yield (new_unit, i[1] * scale, i[2])

# every es resampleo/decimación de la salida de within, son algoritmos de resampling para arriba o abajo.
def every2(time, seq):  # n within t every d
    new_delta = time
    new_count = 0
    old_count = 0
    for i in seq:
        old_delta = i[1]
        if new_count >= old_count + old_delta:
            old_count += old_delta
            continue
        if old_delta <= new_delta:
            yield (i[0], new_delta, i[2])
            new_count += new_delta
            old_count += old_delta
        else:
            old_count += old_delta
            while new_count < old_count and new_count < i[0] - new_delta:
                yield (i[0], new_delta, i[2])
                new_count += new_delta

print( list(within(1, range(3))) )
print( list(every(0.1, range(3))) )
print( list(every2(0.1, within(1, range(3)))) )
print( list(within2(4, every(0.5, range(3)))) )
# ------------------------------------------------------------------------------
