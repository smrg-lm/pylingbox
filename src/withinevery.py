
# ------------------------------------------------------------------------------
# Para triggers:

# Los triggers no necesitan interpolación, no mezclar los dominios.

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
print( list(every2(0.1, within(1, range(3)))) )  # *1
print( list(within2(4, every(0.5, range(3)))) )  # *2

# *1 Este es el caso dentro de m segundos n valores en i pasos, pero está
#    planteado de otra manera dando como dato al período de remuestreo en vez
#    de la cantidad de pasos. Este caso se vuelve incoherente si el período
#    de every2 por la cantidad de elementos de range da una duración mayor
#    a la de within. Si el nuevo período fuera 1 solo entraría el primer valor
#    ¿o saltaría al último como en un range?.
#    Pensarlo como 'in' es más correcto porque el período se deriva de la
#    cantidad de pasos y los valores por decimación.
#    Como venía pensado no debería alargar la duración para ciertos casos de T,
#    es un bug.

# *2 Este último caso es preciso. En 4 segundos 3 valores cada 0.5 no tiene
#    sentido, 3 valores cada 0.5 es en 1.5 segundos. Estaba pensado como
#    que la secuencia que venía dada era de 3 valores cada 0.5 y la duración
#    implícita es de 1.5, al transformar con within cambia la duración de 1.5
#    a 4 y los 3 valores se distribuyen en 4 en vez de 1.5.

# *** VER LOS APUNTES PORQUE TAMBIÉN SE PUEDE PENSAR COMO 'IN' QUE RESAMPLEA
# *** Y COMO RANGO. EL PROBLEMA SON LAS DISTINTAS FORMAS DE PENSARLO SEGÚN LA
# *** NECESIDAD DEL DATO AL QUE SE LE PRESTE MAYOR IMPORTANCIA.

# *** ADEMÁS TIENEN QUE HABER FUNCIONES QUE CALCULEN TEMPO VARIABLES (ACC/RIT).
# *** POR EJEMPLO, UNA PULSACIÓN QUE SE ACELERE DE MM90 A MM120 EN N SEGUNDOS
# *** O EN N PULSOS. Y QUE LOS VALORES DE LOS TRIGGERS PUEDEN SER SECUENCIAS
# *** (ESTO ESTÁ ÚLTIMO ESTÁ RELACIONADO AL CAMBIO DE TEMPO PERO COMO RITMO).
# *** O LOS CORCHETES DIVERGENTES (gettatos accelerando) UNA CANTIDAD DE NOTAS
# *** EN UNA UNIDAD DE TIEMPO PERO ACCELERANDO O RITARDANDO.

# ------------------------------------------------------------------------------


def insteps(dur, steps, seq):
    # La secuencia seq en n pasos durante s segundos. Es resampleo.
    # Es un 'range de una secuencia sin interpolación'. Es similar a *1.
    # ¿En qué casos musicales se requiere esta forma de pensar?
    delta = dur / steps
    dindex = len(seq) / steps
    for n in range(steps):
        yield (dur, delta, seq[int(n * dindex)])

print( list(insteps(1, 13, range(3))) )


def acc(t1, t2, seq, semi=False):
    # tal vez todos los intervalos deberían ser abiertos? como abajo?
    l = len(seq)
    dt = t2 - t1
    it = dt / (l - (1 if semi else 0))
    unit = sum(1 / (t1 + it * i) for i in range(l))
    for i, value in enumerate(seq):
        yield (unit, 1 / (t1 + it * i), value)

list( acc(1, 2, [1, 2, 3]) )
list( acc(1, 2, [1, 2, 3], True) )


def acc2(t1, t2, secs):
    ...


def easing(t1, t2, factor):
    # t1 < t2
    # la cantidad de pasos depende del factor.
    # intervalo abierto.
    while t1 <= (t2 - factor):
        t1 += (t2 - t1) * factor
        yield t1

for i, value in enumerate(easing(1, 4, 0.1)):
    print(i, value)


def expmov(t1, t2, step, exp):
    # exp > 0
    # exp == 1 -> lineal
    # intervalo abierto.
    # mantiene la cantidad de pasos que son entre 0 y 1.
    # step = 1 / stepS # len(seq)
    dist = t2 - t1
    dt = t1
    pct = 0
    while dt < (t2 - step):
        pct += step
        dt = t1 + pct ** exp * dist
        yield dt

list(expmov(1, 4, 0.1, 0.5))
list(expmov(1, 4, 0.1, 1.5))


# sn = n * (a1 + a[n]) / 2  # aritmética
# sn = a1 * (1 - r ** n) / (1 - r)  # r = a[n] / a[n-1], r != 1  # geométrica
# sn = (1 - a ** (n+1)) / (1 - a)  # exponencial
