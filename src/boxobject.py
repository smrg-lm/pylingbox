
from itertools import repeat

from sc3.all import *  # *** BUG: No funciona si import sc3 no se inicializa.
from sc3.base.functions import AbstractFunction
import sc3.seq.stream as stm
import sc3.seq._taskq as tsq
import sc3.synth.node as nod
import sc3.synth.server as srv


# https://stackoverflow.com/questions/26927571/multiple-inheritance-in-python3-with-different-signatures
# https://stackoverflow.com/questions/45581901/are-sets-ordered-like-dicts-in-python3-6

# Hay tres tipos de objetos Box, Trigger y Patch.

# - Nombrar los un/bin/narops aunque sea an __str__
# - Ver cómo se pueden simplificar todas las comprobaciones de tipo BoxObject
#   (isinstance(self.cond, BoxObject)), as_patchobject es la manera sc, hay otra
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
# class TrigFunction(ABC):
#     @abstractmethod
#     def _iter_map(self):
#         pass
#
#     def _iter_value(self):
#         while True:  # *** BoxObject lo tiene que interrumpir.
#             self._obj._clear_cache()
#             yield self._delta
#
#     def __iter__(self):
#         if isinstance(self._obj, TrigFunction):
#             return self._iter_map()
#         else:
#             return self._iter_value()
#
#     def __len__(self):
#         return len(self._obj)
#
#
# class Within(TrigFunction):
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
# class Every(TrigFunction):
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
# s = Seq([1, 2, 3])
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
        if item in self:
            super().remove(item)


class Patch():  # si distintos patch llaman tiran del árbol por medio de los outlets
    current_patch = None

    def __init__(self):
        self._outlets = _UniqueList()
        self._triggers = _UniqueList()
        self._beat = 0.0
        self._cycle = 0
        self._queue = None
        self._routine = None

    @property
    def outlets(self):
        return tuple(self._outlets)

    def play(self, clock=None, quant=None):
        if self._routine:
            return
        def patch_routine():
            yield from self._gen_function()
        self._routine = stm.Routine(patch_routine)
        self._routine.play(clock, quant)
        # *** TODO: La routina podría avisar cuando termina, o no.

    def stop(self):
        if self._routine:
            self._routine.stop()
            # self._routine = None  # Solo se ejecuta una vez.
            # *** TODO: Clear resources if added.
            # Buses tal vez, pero un patch puede correr en un grupo y liberar
            # ese grupo para liberar todo, aunque Routine no se comporta así.

    def _init_queue(self):
        # Evaluación ordenada de los triggers y los outlets.
        self._queue = tsq.TaskQueue()
        for out in self._outlets:
            for trigger in out._get_triggers():
                self._add_trigger(trigger)
        # Acá está la cuestión, el grafo tiene que ser dinámico y se tienen
        # que poder cambiar roots y agregar triggers al vuelo, es agregar
        # nuevos objeto sal scheduler, manteniendo el orden con lo existente,
        # el estado en un momento determinado, es otro tipo de scheduler
        # distinto de tempoclock. El problema también es que los objetos
        # se tienen que evaluar en un instante determinado y no todos al
        # principio.

    def _add_trigger(self, trigger):
        if trigger in self._triggers and trigger._active:
            return
        trigger._active = True
        self._triggers.append(trigger)
        outlets = tuple(
            set(o for obj in trigger._objs for o in obj._outlets if o._active))
        self._queue.add(self._beat + float(trigger._delta), (trigger, outlets))

    def _remove_trigger(self, trigger):
        if trigger not in self._triggers:
            return
        if not any(o._active for obj in trigger._objs for o in obj._outlets):
            trigger._active = False  # lo anula en queue.
            self._triggers.remove(trigger)

    def _gen_function(self):
        self._init_queue()

        # Initial outlet evaluation, self._cycle == 0.
        self._evaluate_oulets(self._outlets)

        prev_beat = 0

        while not self._queue.empty():
            evaluables = set()
            beat, (trigger, outlets) = self._queue.pop()
            self._beat = beat

            yield beat - prev_beat
            self._cycle += 1

            if trigger._active and any(o._active for o in outlets):
                next_beat = next(trigger)  # Exception if not inf.
                outlets = tuple(set(o for o in outlets if o._active))
                evaluables.update(outlets)
                self._queue.add(beat + next_beat, (trigger, outlets))  # Tiende a overflow y error por resolución.

            while not self._queue.empty()\
            and round(beat, 9) == round(self._queue.peek()[0], 9):  # Sincroniza pero introduce un error diferente, hay que ver si converge para el delta de cada trigger.
                trigger, outlets = self._queue.pop()[1]

                if trigger._active and any(o._active for o in outlets):
                    next_beat = next(trigger)  # Exception if not inf.
                    outlets = tuple(set(o for o in outlets if o._active))
                    evaluables.update(outlets)
                    self._queue.add(beat + next_beat, (trigger, outlets))  # Tiende a overflow y error por resolución.

            prev_beat = beat

            try:
                self._evaluate_oulets(evaluables)
            except StopIteration:
                if not any(o._active for o in self._outlets):
                    return

    def _evaluate_oulets(self, evaluables):
        try:
            # Patch puede ser context.
            curr_patch = self
            prev_patch = Patch.current_patch
            Patch.current_patch = curr_patch
            for out in evaluables:
                out()
        finally:
            Patch.current_patch = prev_patch


class PatchFunction():
    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        try:
            # Patch puede ser context.
            new_patch = Patch()
            prev_patch = Patch.current_patch
            Patch.current_patch = new_patch
            self.func(*args, **kwargs)
        finally:
            Patch.current_patch = prev_patch
        return new_patch


# Decorator syntax.
def patch(func):
    return PatchFunction(func)


'''
@patch
def test():
    seq1 = Seq([1, 2, 3])
    seq2 = Seq([10, 20, 30, 40])
    seq3 = Seq([100, 200, 300, 400])

    res1 = seq1 + seq2
    res2 = (1000 + seq1) + seq2 + seq3

    trig = Trig(1), Trig(1), Trig(3)
    # trig[0].connect(seq1)
    trig[1].connect(seq2)
    trig[2].connect(seq3)

    Trace(res1)
    Trace(res2)

t = test()
print([out for out in t.outlets])
t.play()
'''


class BoxObject():
    class __NOCACHE(): pass

    def __init__(self):
        self.__patch = Patch.current_patch
        self.__prev_cycle = -1
        self.__cache = self.__NOCACHE
        self.__roots = _UniqueList()
        self.__branches = _UniqueList()
        self.__outlets = _UniqueList()
        self.__triggers = _UniqueList()

    def __iter__(self):
        return self

    def __next__(self):
        raise NotImplementedError(f'{type(self).__name__}.__next__')

    # Tal vez RENOMBRAR, pero ojo que _value de Outlet es otra función llamada por esta a través de next.
    def __call__(self):
        # Patch is a generator function that creates an timed generator
        # iterator. BoxObjects are evaluated by cycle. A cycle is started
        # by any Trig contained in the Patch. BoxObject with triggers
        # are evaluated with it's own Trig's timing by cleaning the cache.
        # BoxObject without a Trig is evaluated by the cycle of
        # something's else Trig if is in its op branch.
        # As consecuencie, if a BoxObject without Trig is in the branch
        # of more than other BoxObject with different Trigs it will be
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
                # return self._cache
                # para patch anidados, *** VER ***
                if self._cached:
                    return self._cache
                else:
                    ret = self._cache = next(self)
                    return ret

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

    def _dyn_add_root(self, obj):
        self._add_root(obj)
        obj._add_branch(self)
        for trigger in self._triggers:
            obj._patch._add_trigger(trigger)

    def _dyn_remove_root(self, obj):
        self._remove_root(obj)
        obj._remove_branch(self)
        for trigger in self._triggers:
            obj._patch._remove_trigger(trigger)


class TriggerObject():
    '''
    Los triggers son iteradores que simplemente retornan una secuencia de floats
    como deltas. No son nodos porque son transversales, no son parte del grafo.
    No necesita los atributos branches, triggers, y caché, y no son evaluables.
    '''
    def __init__(self):
        self._delta = None
        self._objs = []
        self._active = True

    def __iter__(self):
        return self

    def __next__(self):
        for obj in self._objs:
            obj._clear_cache()
        return self._delta

    def connect(self, obj):
        if not obj in self._objs:
            self._objs.append(obj)
            obj._add_trigger(self)

    def disconnect(self, obj):
        if obj in self._objs:
            self._objs.remove(obj)
            obj._remove_trigger(self)


class Trig(TriggerObject):
    def __init__(self, freq):
        super().__init__()
        self._delta = 1.0 / freq


class _EventDelta(TriggerObject):
    def __init__(self, time):
        super().__init__()
        self._delta = float(time)

    def __next__(self):
        for obj in self._objs:
            obj._clear_cache()
        self._active = False
        return self._delta


class Event(BoxObject):
    def __init__(self, time, obj):
        super().__init__()
        self._obj = obj
        self._wait = time > 0.0
        if self._wait:
            self._trig = _EventDelta(time)
            self._trig.connect(self)

    def __next__(self):
        if self._wait:
            self._wait = False
            return
        self._obj._dyn_add_root(self)
        return self._obj()


'''
from boxobject import *

@patch
def p1():
    a = Event(3, Seq([1, 2, 3, 4, 5], trig=Trig(2)))
    Trace(a, trig=Trig(1))

p = p1()
p.play()
'''


class Outlet(BoxObject):
    def __init__(self, graph, trig=None):
        super().__init__()
        self._add_input(graph)
        self._graph = graph
        self._init_outlet()
        if trig:
            trig.connect(self)
        # *** Tal vez cualquier parámetro de un BoxObject podría ser un trig,
        # *** como pongo abajo dur=Every, pero también podría ser dur=Seq, y
        # *** seq es/tiene un trigger. Se me ocurre que de alguna manera
        # *** implícita pero sistemática se puede mutar cualquier patchobject
        # *** a trigger (?).

    def _add_input(self, value):
        if not isinstance(value, Outlet) and isinstance(value, BoxObject):
            value._add_outlet(self)
            value._add_root(self)
            self._add_branch(value)
        else:
            raise ValueError(f'{value} is invalid outlet input')

    def _init_outlet(self):
        self._add_outlet(self)  # *** No estoy seguro si Outlet puede/debe ser su propio Outlet pero se necesitaría para Trig.
        self._patch._outlets.append(self)
        self._active = True

    def _value(self):
        return self._graph()

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
    x = Trig(1)
    y = Trig(1)
    z = Trig(3)
    a = Seq([1, 2, 3], x)
    b = Seq([10, 20, 30, 40], y)
    c = Value(100, z)
    r = a + b + c
    Trace(r)

g = test()._gen_function()
[x for x in g]
'''


class Trace(Outlet):
    def __init__(self, graph, prefix=None, trig=None):
        super().__init__(graph, trig)
        self._prefix = prefix or 'Trace'

    def _value(self):
        value = self._graph()
        print(
            f'{self._prefix}: <{type(self._graph).__name__}, '
            f'{hex(id(self._graph))}>, cycle: {self._patch._cycle}, '
            f'value: {value}')
        return value


class Note(Outlet):
    # noteEvent de sc Event.

    # *** El problema es que así hay que ponerle trigger a cada seq, o un
    # *** trigger a Outlet que tire de los demás (por ciclo). Outlet está con
    # *** trigger ahora, esta clase no está actualizada. la palabra 'trig' la
    # *** estoy usando acá y se usa como SynthDef key arg, problema.

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
    freq = Seq([440, 480, 540, 580] * 2, trig=Trig(1))
    amp = Seq([0.01, 0.1] * 4)  #, trig=Trig(0.4))
    name = Value('ping')
    note = Note(name=name, freq=freq, amp=amp)
    # Trig(3).connect(note)

p = test()
p.play()
'''


class Inlet(BoxObject):
    def __init__(self, patch, index=0):
        super().__init__()
        self._input_patch = patch
        self._index = index
        out = [out for out in patch.outlets if type(out) is Outlet][index]  # isinstance(out, Outlet)
        # self._input = out._graph
        # self._input._add_root(self)
        # self._add_branch(self._input)
        self._input = out

    def __next__(self):
        return self._input()


''' TEST ACTUAL.
from boxobject import *

@patch
def a():
    freq = Seq([1, 2, 3, 4], Trig(3))
    Trace(freq, 'Seq A')
    Outlet(freq)

@patch
def b():
    pa = a()
    pa.play()

    # freq = Inlet(pa)
    # Trace(freq, 'Inlet', Trig(1))

    freq2 = Seq([10, 20, 30])
    Trace(freq2, 'Seq B', Trig(1))

pb = b()
pb.play()
# Hay el BUG de print en ipython, el timing de las rutinas no se altera
# el problema es que retiene el la escritura a stdout (y luego tira
# Exception None, además).
'''


class Message(BoxObject):
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


class AbstractBox(BoxObject, AbstractFunction):
    def _compose_unop(self, selector):
        return UnopBox(selector, self)

    def _compose_binop(self, selector, other):
        return BinopBox(selector, self, other)

    def _rcompose_binop(self, selector, other):
        return BinopBox(selector, other, self)

    def _compose_narop(self, selector, *args):
        return NaropBox(selector, self, *args)


class UnopBox(AbstractBox):
    def __init__(self, selector, a):
        super().__init__()
        self.selector = selector
        self.a = a
        a._add_root(self)
        self._add_branch(a)

    def __next__(self):
        return self.selector(self.a())


class BinopBox(AbstractBox):
    def __init__(self, selector, a, b):
        super().__init__()
        self.selector = selector
        self.a = a
        self.b = b
        for obj in a, b:
            if isinstance(obj, BoxObject):
                obj._add_root(self)
                self._add_branch(obj)

    def __next__(self):
        a = self.a() if isinstance(self.a, BoxObject) else self.a
        b = self.b() if isinstance(self.b, BoxObject) else self.b
        return self.selector(a, b)


class NaropBox(AbstractBox):
    def __init__(self, selector, a, *args):
        super().__init__()
        self.selector = selector
        self.a = a
        self.args = args
        a._add_root(self)
        self._add_branch(a)
        for obj in args:
            if isinstance(obj, BoxObject):
                obj._add_root(self)
                self._add_branch(obj)

    def __next__(self):
        args = [obj() if isinstance(obj, BoxObject)\
                else obj for obj in self.args]
        return self.selector(self.a(), *args)


class If(AbstractBox):
    def __init__(self, cond, true, false):
        super().__init__()
        self.cond = cond
        self._check_fork(true, false)
        self.fork = (true, false)
        for obj in cond, true, false:  # *** el trigger del brazo inactivo va a seguir andando, no se si está bien o mal.
            if isinstance(obj, BoxObject):
                obj._add_root(self)
                self._add_branch(obj)

    def _check_fork(self, *fork):
        for b in fork:
            if isinstance(b, Outlet) or hasattr(b, '_outlets') and b._outlets:
                raise ValueError("true/false expressions can't contain outlets")

    def __next__(self):
        cond = self.cond() if isinstance(self.cond, BoxObject)\
               else self.cond
        cond = int(not cond)
        if isinstance(self.fork[cond], BoxObject):
            return self.fork[cond]()
        else:
            return self.fork[cond]


'''
@patch
def test():
    a = Seq([1, 2, 3, 4], trig=Trig(1))
    b = Value(0)
    c = a + b
    i = If(c > 2, Value(True), Value(False))
    Trace(i)

g = test()._gen_function()
next(g)
...
'''


class Value(AbstractBox):
    def __init__(self, value, trig=None):
        super().__init__()
        self._value = value
        if trig:
            trig.connect(self)

    def __next__(self):
        return self._value


'''
@patch
def test():
    a = Value(1)
    b = Value(2)
    c = a + b
    Trace(c, trig=Trig(1))

g = test()._gen_function()
next(g)
...
'''


class Seq(AbstractBox):
    def __init__(self, lst, trig=None):
        super().__init__()
        self._lst = lst
        self._len = len(lst)
        self.__iterator = self._seq_iterator()
        if trig:
            trig.connect(self)

    def _seq_iterator(self):
        # Si fueran iterables en vez de iteradores la pertenecia al patch
        # se puede crear cuando se crea el iterador (de manera diferida),
        # además de poder embeber otros iterables.
        # Un iterador es un iterable que se retorna a si mismo con iter().
        # https://docs.python.org/3/glossary.html#term-iterator
        # https://docs.python.org/3/library/stdtypes.html#typeiter
        for obj in self._lst:
            if isinstance(obj, BoxObject):
                try:
                    obj._dyn_add_root(self)
                    while True:
                         yield obj()
                except StopIteration:
                    pass
                finally:
                    obj._dyn_remove_root(self)
            else:
                yield obj

    def __next__(self):
        return next(self.__iterator)

    def __len__(self):
        return self._len


'''
from boxobject import *

@patch
def p1():
    a = Seq([
        Seq([1, 2], trig=Trig(1)),
        Seq([10, 20], trig=Trig(2)),
        Seq([1000, 2000], trig=Trig(1))
    ], trig=Trig(4))
    Trace(a)  #, trig=Trig(1))

p = p1()
p.play()
'''


class FunctionBox(AbstractBox):
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        for obj in (*args, *kwargs.values()):
            if isinstance(obj, BoxObject):
                obj._add_root(self)

    def __next__(self):
        args = [x() if isinstance(x, BoxObject) else x for x in self.args]
        kwargs = {
            key: value() if isinstance(value, BoxObject) else value\
                 for key, value in self.kwargs.items()}
        return self.func(*args, **kwargs)
