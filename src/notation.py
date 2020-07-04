# Notación Laurson, Tidal, Lilypond.

# + es prolongación (ligadura prolongación, tie en inglés).
# - es silencio de voz.
# , separa visualmente, equivalentes a spacio, son opcionales.

# La notación de ligaduras en relación a las estructuras rítmicas por pulso
# y entre pulso hace posible y coherente el empleo sistemático de las
# estructuras proporcionales como tales.

a = 'note'

p1 = [a]
p2 = [a, a]
p3 = [a, a, a, a]
p4 = [a, ['+', a]]
p4r = [[a, a], '+']
p5 = [a, [a, a]]
p5r = [[a, a], a]
p6 = [[a, a], ['+', a]]

p1 = '[a]'
p2 = '[a a]'
p3 = '[a a a a]'
p4 = '[a [+ a]]'
p4r = '[[a a] +]'
p5 = '[a [a a]]'
p5r = '[[a a] a]'
p6 = '[[a a] [+ a]]'

p1 = '|a|'
p2 = '|a a|'
p3 = '|a a a a|'
p4 = '|a |+ a||'
p4r = '||a a| +|'
p5 = '|a |a a||'
p5r = '||a a| a|'
p6 = '||a a| |+ a||'

p1 = '(a)'
p2 = '(a a)'
p3 = '(a a a a)'
p4 = '(a (+ a))'
p4r = '((a a) +)'
p5 = '(a (a a))'
p5r = '((a a) a)'
p6 = '((a a) (+ a))'

p1 = '[a]'
p2 = '[a a]'
p3 = '[a a a a]'
p4 = '[a [+ a]]'
p4r = '[[a a] +]'
p5 = '[a [a a]]'
p5r = '[[a a] a]'
p6 = '[[a a] [+ a]]'

'[a], [a a], [[+ a] a], [[a a] a], [+ a a a], [a]'
'[a, [a a]], [+ [+ a]]'
'[a, [a <a b>]], [<a +> [<- +> b]]'  # lilypond
'[[- a a a], [a a - a], [- [a a]]'
'[a, ([a, a]], [+, [+), a]]'  # lilypond
'[a*4], [a*4], [- a - a], [a]'  # tidal dup


# El parseo básico es simple.

r = 'rest'
s = 'tie'

def _parse_append(value, res, beat):
    if value == 'tie':
        if res:
            res[-1] = (res[-1][0] + beat, res[-1][1])
        else:
            raise ValueError("sequence can't start with tie")  # res.append(([], cell))
    else:
        res.append((beat, value))
    return res

def parse(rhythm, res, beat=1.0):
    for cell in rhythm:
        if isinstance(cell, list):
            if len(cell) > 1:
                res = parse(cell, res, beat / len(cell))
            elif cell:
                res = _parse_append(cell[0], res, beat)
            else:
                raise ValueError('empty cell')
        else:
            res = _parse_append(cell, res, beat)
    return res

'''
parse([[60, [r, 72]], [s, [70, 67], 63]], [])
parse([], [])  # []
parse([[60]], [])  # [(1.0, 60)]
parse([60], [])  # [(1.0, 60)]
parse([60, 62, 63], [])  # [(1.0, 60), (1.0, 62), (1.0, 63)]
parse([60, s, [63, 62]], [])  # [(2.0, 60), (0.5, 63), (0.5, 62)]
seq = parse([60, 66], [])
seq = parse([[s, [67, 61], 66, 62], [63, 65], 64], seq)  # extends, puede comenzar con tie.
'''


# La evaluación diferida es posible reemplazando append por yield pero habría
# que mirar el próximo valor a ver si no es tie, el loop tiene que ir siempre
# una posición adelantado.

r = 'rest'
s = 'tie'

def _lazy_parse_yield(value, prev, beat):
    if value == 'tie':
        if prev:
            return (prev[0] + beat, prev[1])
        else:
            raise ValueError("sequence can't start with tie")
    else:
        if prev:
            yield prev
        return (beat, value)

def lazy_parse(rhythm, prev=None, nested=False, beat=1.0):
    for cell in rhythm:
        if isinstance(cell, list):
            if len(cell) > 1:
                prev = yield from lazy_parse(cell, prev, True, beat / len(cell))
            elif cell:
                prev = yield from _lazy_parse_yield(cell[0], prev, beat)
            else:
                raise ValueError('empty cell')
        else:
            prev = yield from _lazy_parse_yield(cell, prev, beat)
    if nested:
        return prev
    elif prev:
        yield prev

'''
list(lazy_parse([[60, [r, 72]], [s, [70, 67], 63]]))
list(lazy_parse([[60, 60, s], [s, [[s, 62], [s, 63]]]], []))  # [(0.3333333333333333, 60), (1.2916666666666665, 60), (0.25, 62), (0.125, 63)]
list(lazy_parse([]))  # []
list(lazy_parse([[60]]))  # [(1.0, 60)]
list(lazy_parse([60]))  # [(1.0, 60)]
list(lazy_parse([60, 62, 63]))  # [(1.0, 60), (1.0, 62), (1.0, 63)]
list(lazy_parse([60, s, [63, 62]]))  # [(2.0, 60), (0.5, 63), (0.5, 62)]
def extend():
    prev = yield from lazy_parse([60, 66], None, True)
    yield from lazy_parse([[s, [67, 61], 66, 62], [63, 65], 64], prev)  # extends, puede comenzar con tie.
list(extend())
'''


# Notaciones...

R[[C, [rest, G]], [tie, [Bb, D], Eb]]

# Los objetos/clases son singleton.
# Algunas variaciones son demasiado rebuscadas,
# la única que rescato son los cifrados.

Pcs[0, 1, 2]  # este era constructor, podrían ser paréntesis, pero es un vector.

C[0], D[2], E[3], F[4], G[5], A[3], B[0]  # índice

C['^'],  C['.'], Cs['<'], D['>']

C + E + G  # Chord(C, E, G) o vector interválico

C - G  # o intervalo descendente

A.s
A.b, G, F, E.b

F('maj7') / A  # mayor 7 en primera inversión..
F('maj7/A')
F('maj7', A)

C('.'), C('.'), C('-'), C('-')  # articulaciones?


import types


class PitchClass(type):
    def __call__(cls):
        return cls

    # Habría que deshabilitar métodos.
    # def __new__(...):
    #     return cls

    def __int__(cls):
        return cls._pcnum

    def __float__(cls):
        return float(cls._pcnum)

    def __str__(cls):
        return cls.__name__

    def __repr__(cls):
        return cls.__name__


_pc = ['C', 'Cs', 'D', 'Eb', 'E', 'F', 'Fs', 'G', 'Ab', 'A', 'Bb', 'B']
_kwords = {'metaclass': PitchClass}

def _init(pcnum):
    return lambda ns: ns.update({'_pcnum': pcnum})

for i, pc in enumerate(_pc):
    globals().update({pc: types.new_class(pc, (), _kwords, _init(i))})


class Chord():
    ...  # cómo se lleva con la tupla como elemento armónico?


class Voicing():
    # por reglas contrapuntísticas básicas y programables.
    ...
