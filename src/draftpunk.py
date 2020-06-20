
from sc3.all import *


class ObjectValue():
    def __get__(self, obj, cls):
        return obj._ob_value

    def __set__(self, obj, value):
        obj._ob_value = value
        next(obj._outlet)

class BoxObject():
    _ob_value = None  # slot por defecto para los descriptores, no se si así está bien... evita un test en __get__.
    _value = ObjectValue()
    _trig = None  # slot por defecto, pero lo uso para instancias, ver super().__init__ si lo hago.

    def __next__(self):
        return self._value

class trigger(BoxObject):
    def __init__(self, tempo, clock=None):
        self.tempo = tempo
        self.clock = clock or TempoClock.default  # clk.
        self._objects = set()

    def add(self, obj):
        self._objects.add(obj)

    def _run(self):
        self.clock.sched(0, Routine(self._rfunc()))  # stm.

    def _rfunc(self):
        def rfunc():
            while True:
                for obj in self._objects:
                    next(obj)
                yield 1 / self.tempo
        return rfunc

class seq(BoxObject):
    def __init__(self, lst, **kwargs):
        self.lst = lst
        self._iter = iter(lst)
        self._trig = kwargs.get('trig', None)
        if self._trig:  # super().__init__(**kwargs)
            self._trig.add(self)
        self._outlet = None

    def __next__(self):
        self._value = next(self._iter)
        return self._value

class value(BoxObject):
    def __init__(self, value, **kwargs):
        self._value = value
        self._trig = kwargs.get('trig', None)
        if self._trig:  # super().__init__(**kwargs)
            self._trig.add(self)
        self._outlet = None

class outlet(BoxObject):
    def __init__(self, *args, **kwargs):
        self._args = list(args)
        self._triggers = set()
        for obj in self._args:
            obj._outlet = self
            if obj._trig:
                self._triggers.add(obj._trig)
        self._run_triggers()

    def _run_triggers(self):
        def _outlet_rfunc():
            for trig in self._triggers:
                trig._run()
                # tirgger actualiza el valor del objeto que evalúa con next, pero
                # ese objeto tiene que actualizar algo acá, por eso están los
                # descriptores, usan next, pordían no ser generador para outlet.
                # La actualización dummy de outlet está en imprimir.
        # Todos los trigger tienen que salir de la misma Routine para
        # sincronizar el tiempo lógico. La rutina la tiene que crear outlet
        # u otro objeto que actúe como contexto.
        SystemClock.sched(0, Routine(_outlet_rfunc))  # stm.

    def __next__(self):
        print(main.current_tt._seconds, *[x._value for x in self._args])


# Esto va a necesitar un contexto de ejecución, creo.
trig1 = trigger(1)
param1 = seq([60, 62, 63], trig=trig1)
trig2 = trigger(3)
param2 = seq([10, 20, 30], trig=trig2)
# ¿Qué pasa cuando se opera entre dos objetos con diferente trigger?
# Tiene que devolver el valor de estado de cada operando para cada trigger.
outlet(param1, param2)


# ¿Cómo se mezclan funciones y rutinas definidas por le usuario?
# @patch
def func(inlet):  # con introspección posible para los argumentos.
    # Pero esta función no es un BoxObject, y tendría que serlo, creo.
    trig1 = trigger(inlet)
    param1 = seq([60, 62, 63], trig=trig1)
    return param1

outlet(func(1))


# pylingbox
n = numbox()  # intbox, floatbox? Empuja.
r = n * 0.33  # mulop(num, 0.33), en vez de BinaryOpUGen se podría especificar MulOp? (en sc3 también).
# la diferencia entre crear el grafo y ser el grafo.
# crea el grafo:
if r > 10:
    outlet(0, bangbox('gt'))
elif r == 0:
    outlet(0, bangbox('eq'))
elif r < 5:
    outlet(0, bangbox('lt'))
# es el grafo:
ifbox(r < 5, bangbox(msg='lt'))  # crea un objeto ltbox que se conecta a bangbox, no tira.
ifbox(r == 0, bangbox(msg='eq'))  # crea un objeto eqbox que se conecta a bangbox, no tira.
ifbox(r > 10, bangbox(msg='gt'))  # crea un objeto gtbox que se conecta a bangbox, no tira.


@patch
def p():
    m = message('bang')
    a = num(123, inlet=m)
    b = seq([1, 2, 3]) * a
    outlet(b)
p.bang()

t1 = timer(2)
t2 = timer(3)
freq = seq([440 ,880], inlet=t1)  # el problema sigue siendo quién tira y el árbol.
amp = seq([0, 1, 0], inlet=t2)
sine(freq, amp)  # si es un nodo puede actualizar con set, si es un bind crea nodos cada bang.
                 # pero el problema es quién tira! porque así los argumentos empujan.
                 # Los timers/triggers actualizan los valores de los objetos,
                 # pero tiene que haber un objeto outlet que sea la raiz del árbol
                 # de ejecución y que tire cada vez que se actualiza un valor
                 # en los distintos timers.
                 # El problema es la intención de que funcione como reemplazo
                 # de pbind y a la vez como patcher, ahí se genera la confusión
                 # del tira y empuja.


freq = seq([1, 2, 3], within=1)
amp = seq([0.1, 0.5], within=1, every=0.1)
outlet(freq, amp)  # no se necesita par, todo es paralelo por defecto.

notes = seq([1, 2, 3], within=1)
notes = every(0.1, notes)  # si within no fuera múltiplo de every el último beat queda más corto si no alarga la duración...
notes = within(2, notes)  # simplemente expande, la secuencia es finita aunque repita, es la referencia.
value = noise(lo=0.0, hi=1.0, every=0.1)  # si solo se pone within tiene que agregar every por defecto, every tiene sentido para los stream infinitos. Pero puede tener repeats/n además de ser infinito por defecto.
value = within(value, 1)  # ya teniendo every within tiene sentido.
value = repeat(value, 3)
value = concat(value, seq, value, seq)
part = within(7.2, value)
piece = track((0, notes), (1.8, part), (0.7, notes))  # es un conjunto, start+dur, tiempo absoluto.
# se puede llamar time, timeline, track.
# la complejidad se abstraen en las funciones @patch, usa los mismos principios de la programación,
# porque las funciones @patch pueden devolver distintos tipos de objetos (listas, conjuntos, etc.)
# y no solo realizar acciones de ejecución. Así todo se puede componer.

suma = seq([1, 2, 3], within=1) + seq([1, 2, 3], within=2)  # ?


####################################################
# Boceto de organización formal a múltiples escalas.
@synthdef
def note(freq, amp, dur=1):
    env = EnvGen(Env.asr(), scale=amp, stretch=dur, done_action=2)
    sig = SinOsc(freq) * env
    Out(0, sig)

@patch
def melo():
    freq = seq([60, 69, 67, 59], trig(1))
    amp = env([0, 1, 0], within(4))
    outlet(freq, amp)

@patch
def frase():
    # voice sería generador note (como pbind)
    v1 = voice(melo(), within(3))
    v2 = voice(melo() + 1, within(4))
    r = seq([v1, v2])
    outlet(r)

@patch
def forma():
    # forma se puede alterar en duración externamente, por ejemplo.
    s1 = onset(2, frase())
    s2 = onset(3.1, frase())
    outlet(mapa(s1, s2))


#################################
# Otro caso de uso paradigmático:
g1 = Group()
g2 = Group.after(g1)
bus = Bus.audio(s, 2)

@routine
def r():
    fx = Synth('effect', ['inbus', bus], target=g2)
    while True:
        synth = Synth('source', ['outbus', bus], target=g1)
        yield 1

...

@path
def r():
    bus = Bus.audio()
    g1 = Group()
    g2 = Group.after(g1)
    # target no sigue la lógica g1(synth1) u operaciones before/after,
    # se podría hacer? El problema es similar al de los buses, son recursos
    # compartidos/globales. Es el 'parent send' de Reaper y las DAW como
    # opción por defecto.
    fx = effect(bus, target=g2)
    loopbox(lambda: source(bus, target=g1), 1)  # func, wait
    # patch puede liberar los recursos cuando termina,
    # es la función cleanup de los patterns.
    # patch puede organizar conexiones como jitlib, por
    # ejemplo si un patch crea un grupo y un subpatch crea
    # suso nodos dentro de ese grupo, con subnodos, etc.
    # Por cómo es el manejo de los buses, es distinto cuando
    # una synth actúa como entrada de otra, no siempre es
    # preciso escribir fxdef(sinte1), por fxdef lee de un
    # bus que no es una conexión exclusiva entre dos synth.
    #
    # Otra posibilidad es que al crear synths se pueda operar
    # sobre ellas y el orde de ejecución se define por el orden
    # de las operaciones pero, de nuevo, en es directo con el
    # paradigma de los buses, hay que agregar toda la lógica
    # como en jitlib.
    #
    # VER: si los @patch se podrían implementar como definiciones
    # de síntesis, están las demand rate, pero estas serían algo
    # distintas en cuanto a su composición, más programáticas en
    # base al lenguaje de funciones temporales, tal vez como un
    # multirate graph, tal vez sea otro poryecto entero, tal vez
    # los triggers y los outlets deberían actuar según la lógica
    # de los buses/cables, pero ver.
