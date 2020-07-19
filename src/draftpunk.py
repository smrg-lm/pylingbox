
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
def r1():
    fx = Synth('effect', ['inbus', bus], target=g2)
    while True:
        # evento autónomo.
        synth = Synth('source', ['outbus', bus], target=g1)
        yield 1

@routine
def r2():
    fx = Synth('effect', ['inbus', bus], target=g2)
    while True:
        synth = Synth('source', ['outbus', bus], target=g1)
        yield 0.9
        # receptor de instrucciones.
        synth.release()
        yield 0.1

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
    # autónomo (r1)
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

# Message es un objeto útil para el segudo caso, pero no guarda al receptor como tal,
# cotiene el mensaje o es un generador de mensajes que puede estar conectado al receptor.
# Ejemplo de receptor (r2):
v = Violin()
v.noteon(60)
v.noteoff(60)
# Ejemplo de mensaje (r2):
msg = Mensaje()
Cello(msg)
msg.send('noteon', 60)
msg.send('noteoff', 60)
# Secuencia de mensajes a un objeto receptor, como en la segunda rutina (r2):
msg = Message(Seq(['on 60', 'on 72', 'off 60', 'off 72'], Trigger([0.9, 0.1])))
Instrument('cello', msg)
# Incluso:
freq = Midinote(60)
amp = Message('set amp', Env([0, 1, 0]))
Instrument('cello', freq, amp)  # es receptor de mensajes a parámetros
# Así la inversión del flujo es coherente.

# Conjunto de eventos puntuales (con secuencias internas):
# La cuestión es que las tuplas del Map son eventos puntuales.
msgs = Map(
    Event(0, Message('on', 60)),
    Event(1, Message('midinote', Seq([62, 64], trig))),  # función interna iniciada por un evento puntual.
    Event(1, Message('amp', Env([0, 1, 0], within))),  # función interna iniciada por un evento puntual.
    Event(8, Message('off')),
)
Instrument('cello', msgs)
# Se puede reutilizar la palabra Track en el sentido de los multipista como
# línea temporal, tal vez en vez de Map, pero Map está bien también.
# Además un Track es una línea temporal que tiene un Bus y Grupo (como cadena
# de efectos) y reproduce Buffers que genera y procesa señales y las reenvía.
# Un Track es más específico que un Map. Pero, por ejemplo, un instrumento
# vitual se puede poner como plugin de un trac midi que genera los sonidos
# en base a los eventos/mensajes. Un Track también puede ser la realización
# de las señales de control (automatizaciones).

# Tempo, Bpm, Metro (todas refieren a unidad metronómica en bpm o freq).
# Tempo se puede usar como el tempo de las unidades del patch.
# Metro tal vez se puede usar en vez de Trig? No sé.
# Las notaciones R[], Rtm[], etc., pueden crear triggers.

# No perder de vista de que las clases expresan las acciones de manera
# similar a las expresiones de dibujo. Y que representan funciones temporales.
# Ver de qué manera se pueden envolver recursos externos creando clases
# BoxObject (API) o envolviendo como FunctionBox. Se integran con la temporalidad.

# https://stackoverflow.com/questions/26927571/multiple-inheritance-in-python3-with-different-signatures
# https://stackoverflow.com/questions/45581901/are-sets-ordered-like-dicts-in-python3-6

# Hay tres tipos de objetos Box, Trigger y Patch.

# - Nombrar los un/bin/narops aunque sea an __str__
# - Ver cómo se pueden simplificar todas las comprobaciones de tipo BoxObject
#   (isinstance(self.cond, BoxObject)), as_patchobject es la manera sc, hay otra
#   manera funcional?
# - Ver los play de synths.
#   * Son roots, pero hay que ver si pasan el valor, si actúan como salida o
#     subgrafo, si los objetos generados se pasan o almacenan en algún lado.
#   * Hay que tener en cuenta el tipo de abstracción que se crea, si es que se
#     basa en duración constante o instrucciones de ejecución, new, release,
#     la lógica es distinta para duración absoluta o sustain (noteoff/release).
#   * Cuándo el generador es como mono, monoartc o pbind.
#     Cuándo la instrucción que se genera es n_new o n_set, en general.
#     Para algunas cosas se pueden usars grupos como target, scsynth propaga.
# ¿Cuáles son las diferencias entre un grafo de síntesis y un grafo de patcheo?
# Además de que el patcheo está basado en 'eventos' pero se define como flujo
# de eventos, como si fueran señales.

# Pensar estos elementos y las posibles estructuras de datos que se generan
# en relación a Score.

# - Pensar simplemente como lenguaje para la secuenciación en vez de Pbind.
# - Lo importante son los triggers con diferente tempo para las variables.
# - Las synthdef, como funciones que se llama, podrían ser outlets, distintos
#   tipos de roots podrían generar distintos timpos de streams de eventos
#   que creen o no synths, como reemplazo de pbind/pmono/artic.
# - Los valores de repetición de los patterns podrían depender de una variable
#   de configuración que haga que sean infinitos o no (Pattern.repeat = True).
