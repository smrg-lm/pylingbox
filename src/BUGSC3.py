import time
from sc3.all import *

s.boot()

@synthdef
def ping(freq=440):
    env = EnvGen.kr(Env.perc(), done_action=2)
    sig = SinOsc(freq) * 0.01 * env
    Out(0, sig.dup())

t1 = TempoClock()
t2 = TempoClock()

@routine
def ra():
    for i in [1, 2, 3, 4]:
        print(i)
	Synth('ping')
        yield 1/3

@routine
def rb():
    for i in [10, 20, 30]:
        print(i)
	Synth('ping', ['freq', 550])
        yield 1

ra.play(t1)
rb.play(t2)

time.sleep(5)

'''
Es reproducible en ipython. Debería ejecutar:

1
10

2

3

4
20

30

pero ejecuta bien hasta el 4, que sale solo, y
luego salen juntos 20 y 30. El bug puede estar
en el manejos de los hilos, en el loop asincrónico
de ipython en relación a los hilos, el el post
asincrónico de los mensajes de info. Buscar el
problema y entenderlo, buscarlo en sc3 para
solucionarlo. Sucede también sin inicializar
el logger de sc3, este puede no tener que ver.

*** El problema es solo print ***
Las synth tocan a tiempo.
No se soluciona con flush=True.

IPython suele tirar error 'Exception None' y puede
dejar a la terminal sin entrada (la cuelga). Un
ejemplo del error que además provocó un warning:

Press ENTER to continue...                                                                                                              

Unhandled exception in event loop:

Exception None
WARNING: your terminal doesn't support cursor position requests (CPR).

'''
