
from itertools import repeat
from collections import namedtuple

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


class Patch():
    _Entry = namedtuple(
        '_Entry', ['beat', 'next_beat', 'trig', 'messages', 'roots'])
    current_patch = None

    def __init__(self):
        self._outlet = None
        self._roots = _UniqueList()
        self._triggers = _UniqueList()
        self._messages = _UniqueList()
        self._beat = 0.0
        self._cycle = 0
        self._queue = None
        self._routine = None

    @property
    def outlet(self):
        return self._outlet

    @outlet.setter
    def outlet(self, value):
        if self._outlet:
            raise Exception('Patch can only have one Outlet object.')
        self._outlet = value

    @property
    def roots(self):
        return tuple(self._roots)

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
        # Evaluación ordenada de los triggers y las roots.
        self._queue = tsq.TaskQueue()
        for root in self._roots:
            for trigger in root._get_triggers():
                self._add_trigger(trigger)
            for message in root._get_messages():
                self._add_message(message)

    def _add_trigger(self, trigger):
        if trigger in self._triggers and trigger._active:
            return
        trigger._active = True
        self._triggers.append(trigger)
        messages = trigger._get_active_messages()
        roots = trigger._get_active_roots()
        self._queue.add(
            self._beat + float(trigger._delta), (trigger, messages, roots))

    def _remove_trigger(self, trigger):
        if trigger not in self._triggers:
            return
        if not trigger._get_active_messages()\
        or not trigger._get_active_roots():
            trigger._active = False  # lo anula en queue.
            self._triggers.remove(trigger)

    def _add_message(self, message):
        self._messages.append(message)
        for trigger in message._triggers:
            self._add_trigger(trigger)

    def _remove_message(self, message):
        self._messages.remove(message)
        for trigger in message._triggers:
            self._remove_trigger(trigger)

    def _gen_function(self):
        self._init_queue()

        try:
            # Initial RootBox evaluation, self._cycle == 0.
            # Messages are always evaluated before roots within a cycle.
            self._evaluate_cycle(self._messages + self._roots)
        except StopIteration:
            return

        prev_beat = 0

        while not self._queue.empty():
            # Cycle data.

            evaluables = []
            beat, (trigger, messages, roots) = self._queue.pop()

            yield beat - prev_beat
            self._beat = beat
            self._cycle += 1

            # Triggers are evaluated first each cycle (after yield).
            next_beat = next(trigger)  # Triggers are infinite.
            evaluables.append(self._Entry(
                beat, next_beat, trigger, set(messages), set(roots)))

            while not self._queue.empty()\
            and round(beat, 9) == round(self._queue.peek()[0], 9):  # Sincroniza pero introduce un error diferente, hay que ver si converge para el delta de cada trigger.
                trigger, messages, roots = self._queue.pop()[1]
                next_beat = next(trigger)
                evaluables.append(self._Entry(
                    beat, next_beat, trigger, set(messages), set(roots)))

            prev_beat = beat

            # Evaluation.

            messages = []
            roots = []
            for entry in evaluables:
                messages.extend(entry.messages)
                roots.extend(entry.roots)

            try:
                self._evaluate_cycle(messages + roots)
            except StopIteration:
                return

            for entry in evaluables:
                if entry.trig._active\
                and any(r._active for r in entry.messages | entry.roots):
                    newmessages = tuple(m for m in entry.messages if m._active)
                    newroots = tuple(set(r for r in entry.roots if r._active))
                    self._queue.add(  # Tends to error/overflow by resolution.
                        entry.beat + entry.next_beat,
                        (entry.trig, newmessages, newroots))

    def _evaluate_cycle(self, evaluables):
        try:
            # Patch puede ser context.
            exception = False
            curr_patch = self
            prev_patch = Patch.current_patch
            Patch.current_patch = curr_patch
            for out in evaluables:
                try:
                    if out._active:  # Messages deactivate RootBox in its last iteration that is one more for rootboxes.
                        out._evaluate()  # *** También tiene catch and raise interno...
                    else:
                        exception = True
                except StopIteration:
                    exception = True
            if exception:
                if not any(r._active for r in self._messages + self._roots):
                    raise StopIteration
        finally:
            Patch.current_patch = prev_patch


class PatchFunction():
    def __init__(self, func):
        self.func = func

    def __call__(self, *args, play=True, **kwargs):
        try:
            # Patch puede ser context.
            new_patch = Patch()
            prev_patch = Patch.current_patch
            Patch.current_patch = new_patch
            self.func(*args, **kwargs)
        finally:
            Patch.current_patch = prev_patch
        if play:
            new_patch.play()
        return new_patch


# Decorator syntax.
def patch(func):
    return PatchFunction(func)


'''
from boxobject import *

@patch
def test():
    seq1 = Seq([1, 2, 3])
    seq2 = Seq([10, 20, 30, 40], tgg=Trig(1))
    seq3 = Seq([100, 200, 300, 400], tgg=Trig(3))

    res1 = seq1 + seq2
    res2 = (1000 + seq1) + seq2 + seq3

    Trace(res1, 'res1')
    Trace(res2, 'res2')

t = test()
print([out for out in t.roots])
t.play()
'''


class BoxObject():
    class __NOCACHE(): pass

    def __init__(self, tgg=None, msg=None):
        self._active = True
        self.__patch = Patch.current_patch
        self.__prev_cycle = -1
        self.__cache = self.__NOCACHE
        self.__parents = _UniqueList()
        self.__children = _UniqueList()
        self.__roots = _UniqueList()
        self.__messages = _UniqueList()
        self.__triggers = _UniqueList()
        if tgg:
            tgg._connect(self)
        if msg:
            msg._connect(self)

    def __iter__(self):
        return self

    def __next__(self):
        raise NotImplementedError(f'{type(self).__name__}.__next__')

    def _evaluate(self):
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

        if not self._active:
            raise StopIteration

        try:
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
        except StopIteration:
            self._deactivate()
            raise

    def _deactivate(self):
        # By default deactivate all roots,
        # override for special cases.
        self._active = False
        for root in self._roots:
            if root._active:
                root._active = False

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
        for r in self.__parents:
            if r._cached:
                r._clear_cache()

    @property
    def _parents(self):
        return self.__parents

    def _add_parent(self, value):
        self.__parents.append(value)

    def _remove_parent(self, value):
        self.__parents.remove(value)

    def _dyn_add_parent(self, obj):
        self._add_parent(obj)
        obj._add_child(self)
        for trigger in self._triggers:
            obj._patch._add_trigger(trigger)
        for message in self._messages:
            obj._patch._add_message(message)

    def _dyn_remove_parent(self, obj):
        self._remove_parent(obj)
        obj._remove_child(self)
        for trigger in self._triggers:
            obj._patch._remove_trigger(trigger)
        for message in self._messages:
            obj._patch._remove_message(message)

    @property
    def _children(self):
        return self.__children

    def _add_child(self, value):
        self.__children.append(value)

    def _remove_child(self, value):
        self.__children.remove(value)

    @property
    def _roots(self):
        # Las salidas se buscan hacia la raíz.
        ret = _UniqueList()
        for p in self._parents:
            # *** ESTO VA A DEFINIR EL ORDEN DE EJECUCIÓN DE LAS ROOTS.
            # *** VA CAMBIAR SEGÚN QUE NODO LLAME ESTA PROPIEDAD.
            for r in p._roots:
                ret.append(r)
        for r in self.__roots:
            # *** ESTO VA A BARAJAR EL ORDEN DE EJECUCIÓN DE LAS ROOTS PROPIOS.
            ret.append(r)
        return ret

    def _add_root(self, value):
        self.__roots.append(value)

    def _remove_root(self, value):
        self.__roots.remove(value)

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
        for child in self.__children:
            ret.extend(child._get_triggers())
        if self.__triggers:
            ret.extend(self.__triggers)
        return ret

    def _get_triggered_objects(self):
        ret = _UniqueList()
        for child in self.__children:
            ret.extend(child._get_triggered_objects())
        if self.__triggers:
            ret.append(self)
        for message in self.__messages:
            if message._trigger:
                ret.append(message)
        return ret

    @property
    def _messages(self):
        return self.__messages

    def _add_message(self, value):
        self.__messages.append(value)

    def _remove_message(self, value):
        self.__messages.remove(value)

    def _get_msg_recv(self):
        return self

    def _get_messages(self):
        ret = _UniqueList()
        for child in self.__children:
            ret.extend(child._get_messages())
        if self.__messages:
            ret.extend(self.__messages)
        return ret


class TriggerObject():
    '''
    Los triggers son iteradores que simplemente retornan una secuencia de floats
    como deltas. No son nodos porque son transversales, no son parte del grafo.
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

    def _connect(self, obj):
        if not obj in self._objs:
            self._objs.append(obj)
            obj._add_trigger(self)

    def _disconnect(self, obj):  # no se usa?
        if obj in self._objs:
            self._objs.remove(obj)
            obj._remove_trigger(self)

    @property
    def _boxes(self):
        return [o for o in self._objs if isinstance(o, BoxObject)]

    @property
    def _messages(self):
        return [o for o in self._objs if isinstance(o, Message)]

    def _get_active_roots(self):
        roots = set(r for b in self._boxes for r in b._roots if r._active)
        roots |= set(
            r for m in self._messages for o in m._objs\
            for r in o._roots if r._active)
        return tuple(roots)

    def _get_active_messages(self):
        return tuple(m for m in self._messages if m._active)


class Trig(TriggerObject):
    def __init__(self, freq):
        super().__init__()
        self._delta = 1.0 / freq


# Tempo, Bpm, Metro (todas refieren a unidad metronómica en bpm o freq).
# Tempo se puede usar como el tempo de las unidades del patch.
# Metro tal vez se puede usar en vez de Trig? No sé.
# Las notaciones R[], Rtm[], etc., pueden crear triggers.


# class Cleanup() como resource manager.
# g = Group()
# Cleanup(g, delay=2)


# No perder de vista de que las clases expresan las acciones de manera
# similar a las expresiones de dibujo. Y que representan funciones temporales.
# Ver de qué manera se pueden envolver recursos externos creando clases
# BoxObject (API) o envolviendo como FunctionBox. Se integran con la temporalidad.


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
            self._trigger = _EventDelta(time)
            self._trigger._connect(self)

    def __next__(self):
        if self._wait:
            self._wait = False
            return
        self._obj._dyn_add_parent(self)
        return self._obj._evaluate()


'''
from boxobject import *

@patch
def p1():
    a = Event(3, Seq([1, 2, 3, 4, 5], tgg=Trig(4)))
    Trace(a, tgg=Trig(1))

p = p1()
p.play()
'''


class RootBox(BoxObject):
    def __init__(self, tgg=None, msg=None):
        super().__init__(tgg, msg)
        self._patch._roots.append(self)
        self._add_root(self)  # Needed for triggers.

    def _add_input(self, value):
        if not isinstance(value, RootBox) and isinstance(value, BoxObject):
            value._add_root(self)
            value._add_parent(self)
            self._add_child(value)
        else:
            raise ValueError(f'{value} is invalid RootBox input')

    # def _deactivate(self):
        # except StopIteration:
        #     self._active = False
        #     # for obj in self._get_triggered_objects():
        #     #     if not any(r._active for r in obj._roots):  # No active root for this obj.
        #     #         for t in obj._triggers:
        #     #             if not any(r._active for o in t._objs for r in o._roots):  # No active root for other trigger objs.
        #     #                 t._active = False
        #     # raise
        #     for trigger in self._triggers:
        #         # No other active root for the trigger(s) of this root.
        #         if not any(r._active for o in trigger._objs for r in o._roots):
        #             trigger._active = False
        #     raise


class Outlet(RootBox):
    def __init__(self, value, tgg=None):
        super().__init__(tgg)
        self._patch.outlet = self
        if isinstance(value, (list, tuple)):
            self._value = ValueList(value)
        elif not isinstance(value, ValueList):
            self._value = ValueList([value])
        self._add_input(self._value)

    def __next__(self):
        return self._value._evaluate()

    def __getitem__(self, index):
        return self._value[index]

    def __iter__(self):
        # As iterable behaves different.
        return iter(self._value)

    def __len__(self):
        return len(self._value)


class ValueList(BoxObject):
    def __init__(self, lst):
        super().__init__()
        self._lst = []
        self._len = len(lst)
        for obj in lst:
            obj._add_parent(self)
            self._add_child(obj)
            self._lst.append(obj)

    def __next__(self):
        ret = []
        ended = 0
        for value in self._lst:
            try:
                ret.append(value._evaluate())
            except StopIteration:
                ret.append(None)
                ended += 1
        if ended == self._len:
            raise StopIteration
        return ret

    def __getitem__(self, index):
        return self._lst[index]

    def __iter__(self):
        # As iterable behaves different.
        return iter(self._lst)

    def __len__(self):
        return self._len


'''
from boxobject import *

@patch
def outlst():
    a = Seq([1, 2, 3, 4], Trig(1))
    b = Seq([10, 20, 30, 40], Trig(2))
    c = Seq([100, 200, 300, 400], Trig(3))
    o = Outlet([a, b, c])
    # Trace(o[0])
    # a, b, c = o
    # Trace(ValueList([a, b, c]))

@patch
def inlst():
    # a = Inlet(outlst())
    # Trace(a, tgg=Trig(3))

    # a = Inlet(outlst(), 0)
    # Trace(a, tgg=Trig(3))

    # lst = Inlet(outlst(), slice(2))
    # Trace(lst, tgg=Trig(3))

    # a = Inlet(outlst())[0]
    # Trace(a, tgg=Trig(3))

    # a, b, c = Inlet(outlst())
    # Trace(ValueList([a, b, c]), tgg=Trig(3))

    lst = Inlet(outlst())
    Trace(ValueList([*lst]), tgg=Trig(3))

# outlst()
inlst()
'''


class Trace(RootBox):
    def __init__(self, graph, prefix=None, tgg=None, msg=None):
        super().__init__(tgg, msg)
        self._graph = graph
        self._prefix = prefix or 'Trace'
        self._add_input(graph)

    def __next__(self):
        value = self._graph._evaluate()
        print(
            f'{self._prefix}: <{type(self._graph).__name__}, '
            f'{hex(id(self._graph))}>, cycle: {self._patch._cycle}, '
            f'value: {value}')
        return value


'''
@patch
def test():
    a = Seq([1, 2, 3], Trig(1))
    b = Seq([10, 20, 30, 40], Trig(1))
    c = Value(100, Trig(3))
    r = a + b + c
    Trace(r)

test()
'''


class Note(RootBox):
    # noteEvent de sc Event.

    # *** Considerar polirritmia lineal y real (melódica y armónica).
    # *** ¿Los trig se podrían componer como un solo generador (&, ||, ??)?
    # *** ¿Se podría escribir Note(dur=Every(0.5))?

    def __init__(self, *args, **kwargs):
        super().__init__()
        self._params = dict()
        for i, v in enumerate(args, 0):
            self._add_input(v)
            self._params[i] = v
        for k, v in kwargs.items():
            self._add_input(v)
            self._params[k] = v

    def __next__(self):
        ...  # bundle
        params = {k: v._evaluate() for k, v in self._params.items()}
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
    freq = Seq([440, 480, 540, 580] * 2, tgg=Trig(1))
    amp = Seq([0.01, 0.1] * 4)  #, tgg=Trig(0.4))
    name = Value('ping')
    note = Note(name=name, freq=freq, amp=amp)
    # Trig(3)._connect(note)

p = test()
'''


class Inlet(BoxObject):
    def __init__(self, patch, index=None):
        super().__init__()
        self._input_patch = patch
        self._input = patch.outlet
        self._index = index if index is not None else slice(len(patch.outlet))

    def __next__(self):
        if self._input and self._input._active:
            return self._input._cache[self._index]
        else:
            raise StopIteration

    def __getitem__(self, index):
        return type(self)(self._input_patch, index)

    def __iter__(self):
        # As iterable behaves different.
        return (type(self)(self._input_patch, i) for i in range(len(self)))

    def __len__(self):
        return len(self._input)


'''
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

    freq = Inlet(pa)
    Trace(freq, 'Inlet', Trig(1))

    freq2 = Seq([10, 20, 30])
    Trace(freq2, 'Seq B', Trig(1))

pb = b()
pb.play()
# Hay el BUG de print en ipython, el timing de las rutinas no se altera
# el problema es que retiene el la escritura a stdout (y luego tira
# Exception None, además).
'''


class Box(BoxObject):  # Hasta ahora es value sin AbstractBox.
    def __init__(self, obj, tgg=None, msg=None):
        super().__init__(tgg, msg)
        self._obj = obj

    def __next__(self):
        return self._obj

    def _get_msg_recv(self):
        return self._obj


class Message():
    def __init__(self, lst, tgg, bang=True):
        self._active = True  # Evaluable junto con rootbox.
        self._lst = lst
        self.__iterator = iter(lst)
        self.__triggers = _UniqueList()
        tgg._connect(self)
        self._bang = bang
        self._objs = []

    # - Opción 1: Que solo se evalúe cuando es trigueado. No se puede "tirar"
    #   de los mensajes. Problema de la evaluación para distintos nodos.
    # - Opción 2: Que genere un trigger en el objeto que recibe el mensaje,
    #   limpia la caché. Esto es un poco más ambiüo, se podría requerir solo
    #   la preparación de un estado llamando a un método. Flag bang.
    # - Opción 3: En relación a las opciones 1 y 2, que esté fuera del árbol de
    #   evaluación, no sería BoxObject y sería una especie de RootNode que se
    #   evalúa antes que estos.
    # - Ver de qué otras maneras se pueden componer mensajes a partir de
    #   secuencias y demás.
    # - Los mensajes, y esto es lo importante, se pueden usar para cambiar el
    #   estado de otros objetos en el grafo, porque el grafo est estático en
    #   cierto sentido, necesita de nodos que generen las llamadas a los métodos
    #   como mensajes. Así todo queda contenido en el grafo.

    def __iter__(self):
        return self

    def __next__(self):
        next_msg = next(self.__iterator)
        next_msg = self._parse(next_msg)
        for obj in self._objs:
            if self._bang:
                obj._clear_cache()
            recv = obj._get_msg_recv()
            getattr(recv, next_msg[0])(*next_msg[1:])  # *** AttributeError
        return next_msg

    def _parse(self, msg):
        # ['selector 1 "2" 3', 'selector 3 2.1']
        # [('selector', 1, '2', 3), ('selector', 3, 2.1)]
        if isinstance(msg, str):
            msg = msg.split()  # *** pueden quedar caracteres válidos que generan expresiones: "60," es una tupla, [1,2,3], etc.
            for i, v in enumerate(msg[1:][:], 1):
                msg[i] = eval(v, dict())  # *** NameError a log.
        return msg

    def _connect(self, obj):
        if not obj in self._objs:
            self._objs.append(obj)
            obj._add_message(self)

    def _disconnect(self, obj):  # no se usa?
        if obj in self._objs:
            self._objs.remove(obj)
            obj._remove_message(self)


    # Needed by _evaluate_cycle.

    def _evaluate(self):
        try:
            return next(self)
        except StopIteration:
            self._deactivate()
            raise

    def _deactivate(self):
        self._active = False
        for trigger in self.__triggers:
            # Disable the trigger if only connected to this message.
            if len(trigger._objs) == 1:
                trigger._active = False
            # Disable rootbox if only has this trigger.
            for root in trigger._get_active_roots():
                if len(root._get_triggers()) < 2:
                    root._active = False


    # Needed by triggers interface.

    def _add_trigger(self, trigger):
        self.__triggers.append(trigger)

    def _remove_trigger(self, trigger):
        self.__triggers.remove(trigger)


    def _clear_cache(self):
        pass


'''
from boxobject import *

class FakeObject():
    def on(self, note, vel=63):
        print('note on!', note, vel)
    def off(self, note, vel=63):
        print('note off!', note, vel)

@patch
def test():
    msg = Message(['on 60 16', 'on 72', 'off 60', 'off 72'], tgg=Trig(1))
    box = Box(FakeObject(), msg=msg)  # Put it in a box.
    Trace(box)  # Outlet(box)

p = test()
'''


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
        a._add_parent(self)
        self._add_child(a)

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
                obj._add_parent(self)
                self._add_child(obj)

    def __next__(self):
        a = self.a._evaluate() if isinstance(self.a, BoxObject) else self.a
        b = self.b._evaluate() if isinstance(self.b, BoxObject) else self.b
        return self.selector(a, b)


class NaropBox(AbstractBox):
    def __init__(self, selector, a, *args):
        super().__init__()
        self.selector = selector
        self.a = a
        self.args = args
        a._add_parent(self)
        self._add_child(a)
        for obj in args:
            if isinstance(obj, BoxObject):
                obj._add_parent(self)
                self._add_child(obj)

    def __next__(self):
        args = [obj._evaluate() if isinstance(obj, BoxObject)\
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
                obj._add_parent(self)
                self._add_child(obj)

    def _check_fork(self, *fork):
        for b in fork:
            if isinstance(b, Outlet) or hasattr(b, '_roots') and b._roots:
                raise ValueError("true/false expressions can't contain roots")

    def __next__(self):
        cond = self.cond._evaluate() if isinstance(self.cond, BoxObject)\
               else self.cond
        cond = int(not cond)
        if isinstance(self.fork[cond], BoxObject):
            return self.fork[cond]._evaluate()
        else:
            return self.fork[cond]


'''
@patch
def test():
    a = Seq([1, 2, 3, 4], tgg=Trig(1))
    b = Value(0)
    c = a + b
    i = If(c > 2, Value(True), Value(False))
    Trace(i)

g = test()._gen_function()
[value for value in g]
'''


class Value(AbstractBox):
    def __init__(self, value, tgg=None):
        super().__init__(tgg)
        self._value = value

    def __next__(self):
        return self._value


'''
@patch
def test():
    a = Value(1)
    b = Value(2)
    c = a + b
    Trace(c, tgg=Trig(1))

g = test()._gen_function()
for _ in range(10): next(g)
'''


class Seq(AbstractBox):
    def __init__(self, lst, tgg=None):
        super().__init__(tgg)
        self._lst = lst
        self._len = len(lst)
        self.__iterator = self._seq_iterator()

    def _seq_iterator(self):
        # Un iterador es un iterable que se retorna a si mismo con iter().
        # https://docs.python.org/3/glossary.html#term-iterator
        # https://docs.python.org/3/library/stdtypes.html#typeiter
        for obj in self._lst:
            if isinstance(obj, BoxObject):
                try:
                    obj._dyn_add_parent(self)
                    while True:
                         yield obj._evaluate()
                except StopIteration:
                    pass
                obj._dyn_remove_parent(self)
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
        Seq([1, 2], tgg=Trig(1)),
        Seq([10, 20], tgg=Trig(2)),
        Seq([1000, 2000], tgg=Trig(1))
    ], tgg=Trig(4))
    Trace(a)  #, tgg=Trig(1))

p = p1()
p.play()
'''


class FunctionBox(AbstractBox):
    def __init__(self, func, *args, tgg=None, **kwargs):
        super().__init__(tgg)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        for obj in (*args, *kwargs.values()):
            if isinstance(obj, BoxObject):
                obj._add_parent(self)

    def __next__(self):
        args = [
            x._evaluate() if isinstance(x, BoxObject) else x for x in self.args]
        kwargs = {
            key: value._evaluate() if isinstance(value, BoxObject) else value\
                 for key, value in self.kwargs.items()}
        return self.func(*args, **kwargs)
