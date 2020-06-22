# Notación Laurson, Tidal, Lilypond.

# + es prolongación (ligadura)
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
