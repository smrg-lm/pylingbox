
from itertools import repeat

from sc3.all import *  # *** BUG: No funciona si import sc3 no se inicializa.
from sc3.base.functions import AbstractFunction
import sc3.seq._taskq as tsq
import sc3.synth.node as nod
import sc3.synth.server as srv


# https://stackoverflow.com/questions/26927571/multiple-inheritance-in-python3-with-different-signatures
# https://stackoverflow.com/questions/45581901/are-sets-ordered-like-dicts-in-python3-6

# - Nombrar los un/bin/narops aunque sea an __str__
# - Ver cómo se pueden simplificar todas las comprobaciones de tipo PatchObject
#   (isinstance(self.cond, PatchObject)), as_patchobject es la manera sc, hay otra
#   manera funcional?
# - Ver los play de synths.
#   * Son Outlets, pero hay que ver si pasan el valor, si actúan como salida o
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
# - Ver el grafo como iterable (si sirve, el grafo con trig es iterador), pueden
#   ser útiles para generar partituras en nrt (simplemente como iters, sin nrt).

# Pensar estos elementos y las posibles estructuras de datos que se generan
# en relación a Score.

# - Pensar simplemente como lenguaje para la secuenciación en vez de Pbind.
# - Lo importante son los triggers con diferente tempo para las variables.
# - Los outlets pueden ser genéricos o el equivalente a los streams de eventos
#   (pbind), esta interfaz es más bien funcional en vez de declarativa.
# - Las synthdef, como funciones que se llama, podrían ser outlets, distintos
#   tipos de outlets podrían generar distintos timpos de streams de eventos
#   que creen o no synths, como reemplazo de pbind/pmono/artic.
# - Los valores de repetición de los patterns podrían depender de una variable
#   de configuración que haga que sean infinitos o no (Pattern.repeat = True).


# # Para triggers:
# class TriggerFunction(ABC):
#     @abstractmethod
#     def _iter_map(self):
#         pass
#
#     def _iter_value(self):
#         while True:  # *** PatchObject lo tiene que interrumpir.
#             self._obj._clear_cache()
#             yield self._delta
#
#     def __iter__(self):
#         if isinstance(self._obj, TriggerFunction):
#             return self._iter_map()
#         else:
#             return self._iter_value()
#
#     def __len__(self):
#         return len(self._obj)
#
#
# class Within(TriggerFunction):
#     def __init__(self, time, obj):
#         self._unit = time
#         self._delta = time / len(obj)  # *** FALTA EL CASO EVERY.
#         self._obj = obj
#
#     def _iter_map(self):
#         # Within comprime o expande temporalmente la salida de every.
#         # n every d within t (cambia la proporción, nada más). Es recursiva.
#         for delta in iter(self._obj):
#             scale = self._unit / self._obj._unit
#             print(delta, scale, self._unit, self._obj._unit)
#             yield delta * scale
#
#
# class Every(TriggerFunction):
#     def __init__(self, time, obj):
#         self._unit = time * len(obj)  # *** FALTA EL CASO WITHIN.
#         self._delta = time
#         self._obj = obj
#
#     def _iter_map(self):
#         # every es resampleo/decimación de la salida de within,
#         # son algoritmos de resampling para arriba o abajo pero lazy.
#         # n within t every d.
#         new_delta = self._delta
#         new_count = 0
#         old_count = 0
#         for delta in iter(self._obj):
#             old_delta = delta
#             if new_count >= old_count + old_delta:
#                 old_count += old_delta
#                 continue
#             if old_delta <= new_delta:
#                 yield new_delta
#                 new_count += new_delta
#                 old_count += old_delta
#             else:
#                 old_count += old_delta
#                 while new_count < old_count\
#                 and new_count < self._obj._unit - new_delta:
#                     yield new_delta
#                     new_count += new_delta
#
# '''
# s = SeqBox([1, 2, 3])
# x = Within(1, s)
# x = Every(0.1, x)
# # x = Within(3, x)  # llama, pero no está bien el tiempo
# x = iter(x)
# print(next(x), s())
# # se cuelga en el último por el continue de iter_map (caso 1 w y 1 e).
# '''


class _UniqueList(list):
    def append(self, item):
        if item not in self:
            super().append(item)

    def extend(self, iterable):
        for item in iterable:
            super().append(item)

    def remove(self, item):
        if item not in self:
            super().remove(item)


class PatchObject():
    __NOCACHE = object()

    def __init__(self):
        self.__patch = Patch.current_patch
        self.__prev_cycle = -1
        self.__cache = self.__NOCACHE
        self.__roots = _UniqueList()
        self.__branches = _UniqueList()
        self.__outlets = _UniqueList()
        self.__triggers = _UniqueList()

    def __iter__(self):
        raise NotImplementedError(f'{type(self).__name__}.__iter__')

    def __next__(self):
        raise NotImplementedError(f'{type(self).__name__}.__next__')

    # Tal vez RENOMBRAR, pero ojo que _value de Outlet es otra función llamada por esta a través de next.
    def __call__(self):
        # Patch is a generator function that creates an timed generator
        # iterator. PatchObjects are evaluated by cycle. A cycle is started
        # by any Trigger contained in the Patch. PatchObject with triggers
        # are evaluated with it's own Trigger's timing by cleaning the cache.
        # PatchObject without a Trigger is evaluated by the cycle of
        # something's else Trigger if is in its op branch.
        # As consecuencie, if a PatchObject without Trigger is in the branch
        # of more than other PatchObject with different Triggers it will be
        # consumed by the triggers of every shared expression, a copy whould
        # be needed to avoid this. Is it too much compliated?
        if self.__triggers:
            if self._cached:
                return self._cache
            else:
                ret = self._cache = next(self)
                return ret
        else:
            if self._patch._cycle > self.__prev_cycle:
                self.__prev_cycle = self._patch._cycle
                ret = self._cache = next(self)
                return ret
            else:
                return self._cache

    @property
    def _patch(self):
        return self.__patch

    @property
    def _cache(self):
        return self.__cache

    @_cache.setter
    def _cache(self, value):
        self.__cache = value

    @property
    def _cached(self):
        return self.__cache is not self.__NOCACHE

    def _clear_cache(self):
        self.__cache = self.__NOCACHE
        for r in self.__roots:
            if r._cached:
                r._clear_cache()

    @property
    def _roots(self):
        return self.__roots

    def _add_root(self, value):
        self.__roots.append(value)

    def _remove_root(self, value):
        self.__roots.remove(value)

    @property
    def _branches(self):
        return self.__branches

    def _add_branch(self, value):
        self.__branches.append(value)

    def _remove_branch(self, value):
        self.__branches.remove(value)

    @property
    def _outlets(self):
        # Las salidas se buscan hacia la raíz.
        ret = _UniqueList()
        for r in self._roots:
            # *** ESTO VA A DEFINIR EL ORDEN DE EJECUCIÓN DE LOS OUTLETS.
            # *** VA CAMBIAR SEGÚN QUE NODO LLAME ESTA PROPIEDAD.
            for o in r._outlets:
                ret.append(o)
        for o in self.__outlets:
            # *** ESTO VA A BARAJAR EL ORDEN DE EJECUCIÓN DE LOS OUTLETS PROPIOS.
            ret.append(o)
        return ret

    def _add_outlet(self, value):
        self.__outlets.append(value)

    def _remove_outlet(self, value):
        self.__outlets.remove(value)

    @property
    def _triggers(self):
        return self.__triggers

    def _add_trigger(self, value):
        self.__triggers.append(value)

    def _remove_trigger(self, value):
        self.__triggers.remove(value)

    def _get_triggers(self):
        # Los triggers se buscan hacia las hojas.
        ret = _UniqueList()
        for branch in self.__branches:
            ret.extend(branch._get_triggers())
        for trigger in self.__triggers:
            ret.append(trigger)
        return ret

    def _get_triggered_objects(self):
        ret = _UniqueList()
        for branch in self.__branches:
            ret.extend(branch._get_triggered_objects())
        if self.__triggers:
            ret.append(self)
        return ret


class Patch():  # si distintos patch llaman tiran del árbol por medio de los outlets
    current_patch = None

    def __init__(self):
        self._outlets = []
        self._cycle = 0

    @property
    def outlets(self):
        return self._outlets

    def play(self):
        # Evaluación ordenada de los triggers y los outlets.
        queue = tsq.TaskQueue()
        for out in self._outlets:
            for trigger in out._get_triggers():
                outlets = tuple(o for obj in trigger._objs for o in obj._outlets)
                queue.add(float(trigger._delta), (iter(trigger), outlets))

        # Initial outlet evaluation, self._cycle == 0.
        print(f'cycle {self._cycle} ---------------------------------')
        for out in self._outlets:
            out()

        prev_delta = 0
        while not queue.empty():
            evaluables = set()
            delta, (trigger, outlets) = queue.pop()
            yield delta - prev_delta
            self._cycle += 1
            next_delta = next(trigger)  # Exception if not inf.
            evaluables.update(outlets)
            queue.add(delta + next_delta, (trigger, outlets))  # Tiende a overflow y error por resolución.
            while not queue.empty()\
            and round(delta, 9) == round(queue.peek()[0], 9):  # Sincroniza pero introduce un error diferente, hay que ver si converge para el delta de cada trigger.
                trigger, outlets = queue.pop()[1]
                next_delta = next(trigger)  # Exception if not inf.
                evaluables.update(outlets)
                queue.add(delta + next_delta, (trigger, outlets))
            prev_delta = delta

            try:
                # Outlet evaluation.
                print(f'cycle {self._cycle} ---------------------------------')
                for out in evaluables:
                    out()
            except StopIteration:
                return

'''
@patch
def test():
    seq1 = SeqBox([1, 2, 3])
    seq2 = SeqBox([10, 20, 30, 40])
    seq3 = SeqBox([100, 200, 300, 400])

    res1 = seq1 + seq2
    res2 = (1000 + seq1) + seq2 + seq3

    trig = Trigger(1), Trigger(1), Trigger(3)
    # trig[0].connect(seq1)
    trig[1].connect(seq2)
    trig[2].connect(seq3)

    Outlet(res1)
    Outlet(res2)

print([id(out) for out in test.outlets])

@routine
def r():
    yield from test.play()

r.play()
'''


def patch(func):
    # *** Hay que pensar Patch como  una función generadora, tiene que crear
    # *** nuevas instancias cada vez que se evalúa, no acá.
    # SE PUEDE USAR CONTEXT MANAGER PARA EVITAR QUE CURRENT_PATCH QUEDE
    # INCONSISTENTE SI FALLA LA EVALUACIÓN DE FUNC(). VER SYNTHDEF PERO
    # CREO QUE TIENE TRY/EXCEPT.
    try:
        pch = Patch()
        Patch.current_patch = pch
        func()
    except:
        Patch.current_patch = None
        raise
    return pch


class Trigger():
    '''
    Un trigger no es un nodo porque no necesita los atributos branches,
    triggers, y caché, y no son evaluables. No es necesario que hereden
    toda la maquinaria de PatchObject.
    Los triggers son iterables que simplemente retornan una secuencia de floats
    como deltas, los nodos PatchObject son tanto iteradores (__next__) como
    iterables, pero cuando son usados como iterables los triggers se ignoran,
    no forma parte del árbol de evaluación.
    '''
    def __init__(self, freq):
        self._delta = 1.0 / freq
        self._objs = []
        self._active = True

    def __iter__(self):
        while True:
            if not self._active:
                return
            for obj in self._objs:
                obj._clear_cache()
            yield self._delta

    def connect(self, obj):
        if not obj in self._objs:
            self._objs.append(obj)
            obj._add_trigger(self)

    def disconnect(self, obj):
        if obj in self._objs:
            self._objs.remove(obj)
            obj._remove_trigger(self)


'''
s = SeqBox([1, 2, 3])
x = Trigger(1)
x.connect(s)
x = iter(x)
print(next(x), s())
'''


class Outlet(PatchObject):
    def __init__(self, graph):
        super().__init__()
        self._add_input(graph)
        self._graph = graph
        self._init_outlet()

    def _add_input(self, value):
        if not isinstance(value, Outlet) and isinstance(value, PatchObject):
            value._add_outlet(self)
            value._add_root(self)
            self._add_branch(value)
        else:
            raise ValueError(
                f"'{type(value).__class__}' ({value}) is invalid outlet input")

    def _init_outlet(self):
        self._add_outlet(self)  # *** No estoy seguro si Outlet puede/debe ser su propio Outlet pero se necesitaría para Trigger.
        self._patch._outlets.append(self)
        self._active = True

    def _value(self):
        return self._graph()

    def __iter__(self):
        yield from self._graph

    def __next__(self):
        try:
            return self._value()
        except StopIteration:
            self._active = False
            for obj in self._get_triggered_objects():
                if not any(o._active for o in obj._outlets):  # No active outlet for this obj.
                    for trigger in obj._triggers:
                        if not any(
                        o._active for tobj in trigger._objs\
                        for o in tobj._outlets):  # No active outlet for other trigger objs.
                            trigger._active = False
            raise


'''
@patch
def test():
    x = Trigger(1)
    y = Trigger(1)
    z = Trigger(3)
    a = SeqBox([1, 2, 3], x)
    b = SeqBox([10, 20, 30, 40], y)
    c = ValueBox(100, z)
    r = a + b + c
    Outlet(r)

outs = test._outlets
g = outs[0].play()
[x for x in g]
'''

'''
@patch
def test():
    a = SeqBox([1, 2, 3])
    b = ValueBox(10)
    c = ValueBox(100)
    r1 = a * b
    r2 = a * b + c
    d = SeqBox([1, 2, 3, 4])
    r3 = d * 1000
    x = Trigger(1)
    x.connect(a)
    x.connect(d)
    Outlet(r1)
    Outlet(r2)
    Outlet(r3)

outs = test._outlets
trig = outs[0]._get_triggers()[0]
itrig = iter(trig)

for i in range(3):
    for o in outs:
        print(o())
    next(itrig)

# outs[0]()  # StopIteration
# outs[1]()  # StopIteration
# outs[2]()  # 4000
# trig._active  # True
# next(itrig)  # 1
# outs[2]()  # StopIteration
# trig._active  # False
'''


class Note(Outlet):
    # noteEvent de sc Event.

    # *** El problema es que así hay que ponerle trigger a cada seq.
    # *** CONSIDERAR POLIRRITMIA LINEAL Y REAL (melódica y armónica).
    # *** LOS TRIG TAMBIÉN SE PODRÍAN COMPONER EN UNO SOLO CON UN OPERADOR ARITMÉTICO (&, ||, ??)
    # *** ALGO QUE ES CONFUSO ES QUE LOS TRIGGERS NO PUEDEN ESTAR EN OUTLET, PORQUE NO LIMPIA LA CACHE,
    # *** SE PODRÍA HACER QUE LA LIMPIE HACIA LAS HOJAS CUANDO EVALÚA, PERO QUÉ PASA CON LOS NODOS
    # *** QUE SON SEQ PERO NO ESTÁ RELACIONADOS POR OPERACIÓN, NO RECUERDO POR LA PAUSA EN EL DESARROLLO.
    # *** Y QUÉ PASA SI NO SE QUIERE PONER TRIGGER EN NINGÚN/CADA PARÁMETRO, TRIGGER PODRÍA SER UN
    # *** BOXOBJECT? PORQUE SE PODRÍA ESCRIBIR Note(dur=Every(0.5)).
    # *** PLAY DEBERÍA CREAR NUEVAS INSTANCIAS DEL PATCH Y SUS OBJETOS COMO LAS FUNCIONES GENERADORAS.

    def __init__(self, *args, **kwargs):
        super(Outlet, self).__init__()
        self._params = dict()
        for i, v in enumerate(args, 0):
            self._add_input(v)
            self._params[i] = v
        for k, v in kwargs.items():
            self._add_input(v)
            self._params[k] = v
        self._init_outlet()

    def _value(self):  # *** va a ser intefaz de outlet, se llama desde next, tengo problemas con los nombres, next, call, value, poruqe outlet evalúa distinto.
        ...  # bundle
        params = {k: v() for k, v in self._params.items()}
        def_name = params.pop('name', 'default')
        target = params.pop('target', None)
        add_action = params.pop('add_action', 'addToHead')
        register = params.pop('register', None)
        args = [i for t in params.items() for i in t]
        print('+++', args)
        synth = nod.Synth(def_name, args, target, add_action, register)
        ... # release en base a dur msg.
        ... # bundle
        ... # send
        return synth

'''
s.boot()

@synthdef
def ping(freq=440, amp=0.1):
    sig = SinOsc(freq) * amp
    env = EnvGen.kr(Env.perc(), done_action=Done.FREE_SELF)
    Out(0, (sig * env).dup())

# después...

@patch
def test():
    freq = SeqBox([440, 480, 540, 580] * 2, trig=Trigger(1))
    amp = SeqBox([0.01, 0.1] * 4)  #, trig=Trigger(0.4))
    name = ValueBox('ping')
    note = Note(name=name, freq=freq, amp=amp)
    # Trigger(3).connect(note)

@routine.run()
def r():
    yield from test.play()
'''


class Inlet(PatchObject):
    def __init__(self, value):
        self._value = value
        value._add_root(self)
        self._add_branch(value)

    def __iter__(self):
        if isinstance(self._value, PatchObject):
            yield from self._value
        else:
            while True:
                yield self._value

    def __next__(self):
        if isinstance(self._value, PatchObject):
            return next(self._value)
        else:
            return self._value


class Message(PatchObject):
    # Tiene branches porque puede contener secuencias y next evalúa los
    # métodos de root. connect/disconnect tal vez no sean necesarios.
    # Ver de qué otras maneras se pueden componer mensajes a partir de
    # secuencias y demás, tal vez simplemente dependa del objeto de destino
    # como venía pensando, pero ver bien.
    # Los mensajes, y esto es lo importante, se pueden usar para cambiar el
    # estado de otros objetos en el grafo, porque el grafo est estático en
    # cierto sentido, necesita de nodos que generen las llamadas a los métodos
    # como mensajes. Así todo queda contenido en el grafo.
    def __init__(self, *msg):
        super().__init__()
        self.msg = msg

    def connect(self, target):
        self._add_root(target)

    def disconnect(self, target):
        self._remove_root(target)


class AbstractBox(PatchObject, AbstractFunction):
    def _compose_unop(self, selector):
        return UnaryOpBox(selector, self)

    def _compose_binop(self, selector, other):
        return BinaryOpBox(selector, self, other)

    def _rcompose_binop(self, selector, other):
        return BinaryOpBox(selector, other, self)

    def _compose_narop(self, selector, *args):
        return NAryOpBox(selector, self, *args)


class UnaryOpBox(AbstractBox):
    def __init__(self, selector, a):
        super().__init__()
        self.selector = selector
        self.a = a
        a._add_root(self)
        self._add_branch(a)

    def __iter__(self):
        for value in self.a:
            yield self.selector(value)

    def __next__(self):
        return self.selector(next(self.a))


class BinaryOpBox(AbstractBox):
    def __init__(self, selector, a, b):
        super().__init__()
        self.selector = selector
        self.a = a
        self.b = b
        for obj in a, b:
            if isinstance(obj, PatchObject):
                obj._add_root(self)
                self._add_branch(obj)

    def __iter__(self):
        ia = self.a if isinstance(self.a, PatchObject) else repeat(self.a)
        ib = self.b if isinstance(self.b, PatchObject) else repeat(self.b)
        for a, b in zip(ia, ib):
            yield self.selector(a, b)

    def __next__(self):
        a = self.a() if isinstance(self.a, PatchObject) else self.a
        b = self.b() if isinstance(self.b, PatchObject) else self.b
        return self.selector(a, b)


class NAryOpBox(AbstractBox):
    def __init__(self, selector, a, *args):
        super().__init__()
        self.selector = selector
        self.a = a
        self.args = args
        a._add_root(self)
        self._add_branch(a)
        for obj in args:
            if isinstance(obj, PatchObject):
                obj._add_root(self)
                self._add_branch(obj)

    def __iter__(self):
        args = [obj if isinstance(obj, PatchObject)\
                else repeat(obj) for obj in self.args]
        for a, *args in zip(self.a, *args):
            yield self.selector(a, *args)

    def __next__(self):
        args = [next(obj) if isinstance(obj, PatchObject)\
                else obj for obj in self.args]
        return self.selector(next(self.a), *args)


class IfBox(AbstractBox):
    def __init__(self, cond, true, false):
        super().__init__()
        self.cond = cond
        self._check_fork(true, false)
        self.fork = (true, false)
        for obj in cond, true, false:
            if isinstance(obj, PatchObject):
                obj._add_root(self)
                self._add_branch(obj)

    def _check_fork(self, *fork):
        for b in fork:
            if isinstance(b, Outlet) or hasattr(b, '_outlets') and b._outlets:
                raise ValueError("true/false expressions can't contain outlets")

    def __iter__(self):
        true, false = [obj if isinstance(obj, PatchObject) else repeat(obj)\
                       for obj in self.fork]
        if isinstance(self.cond, PatchObject):
            for cond, true, false in zip(self.cond, true, false):
                if cond:
                    yield true
                else:
                    yield false
        else:
            if self.cond:
                yield from true
            else:
                yield from false

    def __next__(self):
        cond = next(self.cond) if isinstance(self.cond, PatchObject)\
               else self.cond
        cond = int(not cond)
        if isinstance(self.fork[cond], PatchObject):
            return next(self.fork[cond])
        else:
            return self.fork[cond]


class ValueBox(AbstractBox):
    def __init__(self, value, trig=None):
        super().__init__()
        self._value = value
        if trig:
            trig.connect(self)

    def __iter__(self):
        while True:
            yield self._value

    def __next__(self):
        return self._value


class SeqBox(AbstractBox):
    def __init__(self, lst, trig=None):
        super().__init__()
        self._lst = lst
        self._len = len(lst)
        self._iterator = iter(lst)
        if trig:
            trig.connect(self)

    def __iter__(self):
        yield from self._lst

    def __next__(self):
        return next(self._iterator)

    def __len__(self):
        return self._len

'''
# Grafo de iteradores con call/cache.
a = SeqBox([1, 2, 3])
b = ValueBox(0)
c = a + b
o = Outlet(c)
print(next(o))
print(next(o))
c._clear_cache()  # no reevalúa a y b
print(next(o))
print(next(o))
b._clear_cache()  # no reevalúa a
print(next(o))
a._clear_cache()  # no reevalúa b
print(next(o))
a._clear_cache()
print(next(o))
# ...
# StopIteration
'''

'''
# Grafo de iterables (__iter__). Es UNA de las dos opciones, sin triggers.
a = SeqBox([1, 2, 3])
b = ValueBox(0)
c = a + b
i = IfBox(c > 2, ValueBox(True), ValueBox(False))
o = Outlet(i)

o = iter(o)
print(next(o))
print(next(o))
print(next(o))
# print(next(o))  # StopIteration
'''


class FunctionBox(AbstractBox):
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        for obj in (*args, *kwargs.values()):
            if isinstance(obj, PatchObject):
                obj._add_root(self)

    def __iter__(self):
        args = [obj if isinstance(obj, PatchObject) else repeat(obj)\
                for obj in self.args]
        kwargs = {
            key: value if isinstance(value, PatchObject) else repeat(value)\
                 for key, value in self.kwargs.items()}
        ...  # ?

    def __next__(self):
        args = [next(x) if isinstance(x, PatchObject) else x for x in self.args]
        kwargs = {
            key: next(value) if isinstance(value, PatchObject) else value\
                 for key, value in self.kwargs.items()}
        return self.func(*args, **kwargs)

'''
a = ValueBox(1)
b = ValueBox(2)
c = a + b
o = Outlet(c)

r = iter(o)
next(r)
'''

'''
for obj in a, b, c, o:
    print(hex(id(obj)), obj._outlets, obj._roots)
'''

'''
a = ValueBox(1)
b = ValueBox(0)
c = a + b
i = IfBox(c > 2, ValueBox(True), ValueBox(False))
o = Outlet(i)

o = iter(o)
print(next(o))
b._value = 2
print(next(o))
'''
