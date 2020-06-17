
from itertools import repeat

from sc3.all import *  # *** BUG: No funciona si import sc3 no se inicializa.
from sc3.base.functions import AbstractFunction
import sc3.seq._taskq as tsq


# https://stackoverflow.com/questions/26927571/multiple-inheritance-in-python3-with-different-signatures
# https://stackoverflow.com/questions/45581901/are-sets-ordered-like-dicts-in-python3-6

# - Nombrar los un/bin/narops aunque sea an __str__
# - Los valores de repetición de los patterns podrían depender de una variable
#   de configuración que haga que sean infinitos o no (Pattern.repeat = True).

# - Pensar simplemente como lenguaje para la secuenciación en vez de Pbind.
# - Lo importante son los triggers con diferente tempo para las variables.
# - Los outlets pueden ser genéricos o el equivalente a los streams de eventos
#   (pbind), esta interfaz es más bien funcional en vez de declarativa.
# - Las synthdef, como funciones que se llama, podrían ser outlets, distintos
#   tipos de outlets podrían generar distintos timpos de streams de eventos
#   que creen o no synths, como reemplazo de pbind/pmono/artic.
# - Tal vez mejor no hacer mensajes, descartar la idea de las cajas es adoptar
#   el paradigma más funcional.


# # Para triggers:
# class TriggerFunction(ABC):
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


class BoxObject():
    __NOCACHE = object()

    def __init__(self):
        self.__cache = self.__NOCACHE
        self.__roots = []
        self.__branches = []
        self.__outlets = []
        self.__triggers = []

    def __iter__(self):
        raise NotImplementedError(f'{type(self).__name__}.__iter__')

    def __next__(self):
        raise NotImplementedError(f'{type(self).__name__}.__next__')

    def __call__(self):
        if self._cached:
            return self._cache
        else:
            ret = self._cache = next(self)
            return ret

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
        if not value in self.__roots:
            self.__roots.append(value)

    def _remove_root(self, value):
        if value in self.__roots:
            self.__roots.remove(value)

    @property
    def _branches(self):
        return self.__branches

    def _add_branch(self, value):
        if not value in self.__branches:
            self.__branches.append(value)

    def _remove_branch(self, value):
        if not value in self.__branches:
            self.__branches.remove(value)

    @property
    def _outlets(self):
        # Las salidas se buscan hacia la raíz.
        ret = []
        for r in self._roots:
            # *** ESTO VA A DEFINIR EL ORDEN DE EJECUCIÓN DE LOS OUTLETS.
            # *** VA CAMBIAR SEGÚN QUE NODO LLAME ESTA PROPIEDAD.
            for o in r._outlets:
                if not o in ret:
                    ret.append(o)
        for o in self.__outlets:
            # *** ESTO VA A BARAJAR EL ORDEN DE EJECUCIÓN DE LOS OUTLETS PROPIOS.
            if not o in ret:
                ret.append(o)
        return ret

    def _add_outlet(self, value):
        if not value in self.__outlets:
            self.__outlets.append(value)

    def _remove_outlet(self, value):
        if value in self.__outlets:
            self.__outlets.remove(value)

    @property
    def _triggers(self):
        return self.__triggers

    def _add_trigger(self, value):
        if not value in self.__triggers:
            self.__triggers.append(value)

    def _remove_trigger(self, value):
        if value in self.__triggers:
            self.__triggers.remove(value)

    def _get_triggers(self):
        # Los triggers se buscan hacia las hojas.
        ret = []
        for branch in self.__branches:
            ret.extend(branch._get_triggers())
        for trigger in self.__triggers:
            if not trigger in ret:
                ret.append(trigger)
        return ret

    def _get_triggered_objects(self):
        ret = []
        for branch in self.__branches:
            ret.extend(branch._get_triggered_objects())
        if self.__triggers:
            ret.append(self)
        return ret


class Patch():  # si distintos patch llaman tiran del árbol por medio de los outlets
    current_patch = None

    def __init__(self):
        # self.tree = None  # *** puede haber más de un árbol independiente?
        self._outlets = []

    def _build(self):
        ...

    def play(self):
        # Evaluación ordenada de los triggers y los outlets.
        ...


def patch(func):
    p = Patch()
    Patch.current_patch = p
    func()
    Patch.current_patch = None
    p._build()
    return p


class Trigger():
    def __init__(self, delta):
        self._delta = delta
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


class Outlet(BoxObject):
    def __init__(self, graph):
        super().__init__()
        if not isinstance(graph, Outlet) and isinstance(graph, BoxObject):
            graph._add_outlet(self)
        else:
            raise ValueError(
                f"'{type(graph).__class__}' is not a valid graph object")
        self._graph = graph
        graph._add_root(self)
        self._add_branch(graph)
        self._patch = Patch.current_patch
        self._patch._outlets.append(self)
        self._active = True

    def __iter__(self):
        yield from self._graph

    def __next__(self):
        try:
            return self._graph()
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

    def play(self):
        # Evaluación ordenada de los triggers y los outlets.
        # SE PUEDE HACER PARA UN OUTLET Y LUEGO PARA TODOS LOS OUTLETS DE
        # UN PATCH. LAS DOS OPCIONES SON ÚTILES.
        queue = tsq.TaskQueue()
        for trigger in self._get_triggers():
            queue.add(float(trigger._delta), iter(trigger))
        prev_delta = 0

        print(self())  # Initial outlet evaluation.

        while not queue.empty():
            delta, trigger = queue.pop()
            yield delta - prev_delta
            next_delta = next(trigger)  # Exception.
            queue.add(delta + next_delta, trigger)  # Tiende a overflow y error por resolución.
            while not queue.empty()\
            and round(delta, 9) == round(queue.peek()[0], 9):  # Sincroniza pero introduce un error diferente, hay que ver si converge para el delta de cada trigger.
                trigger = queue.pop()[1]
                next_delta = next(trigger)  # Exception.
                queue.add(delta + next_delta, trigger)
            prev_delta = delta

            try:
                print(self())  # Outlet evaluation.
            except StopIteration:
                return

'''
@patch
def test():
    a = SeqBox([1, 2, 3])
    b = SeqBox([10, 20, 30, 40])
    c = ValueBox(100)
    r = a + b + c
    x = Trigger(1)
    y = Trigger(1)
    z = Trigger(0.3)
    x.connect(a)
    y.connect(b)
    z.connect(c)
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


class Inlet(BoxObject):
    def __init__(self, value):
        self._value = value
        value._add_root(self)
        self._add_branch(value)

    def __iter__(self):
        if isinstance(self._value, BoxObject):
            yield from self._value
        else:
            while True:
                yield self._value

    def __next__(self):
        if isinstance(self._value, BoxObject):
            return next(self._value)
        else:
            return self._value


class Message(BoxObject):
    def __init__(self, *msg):
        super().__init__()
        self.msg = msg

    def connect(self, target):
        self._add_root(target)

    def disconnect(self, target):
        self._remove_root(target)


class AbstractBox(BoxObject, AbstractFunction):
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
            if isinstance(obj, BoxObject):
                obj._add_root(self)
                self._add_branch(obj)

    def __iter__(self):
        ia = self.a if isinstance(self.a, BoxObject) else repeat(self.a)
        ib = self.b if isinstance(self.b, BoxObject) else repeat(self.b)
        for a, b in zip(ia, ib):
            yield self.selector(a, b)

    def __next__(self):
        a = self.a() if isinstance(self.a, BoxObject) else self.a
        b = self.b() if isinstance(self.b, BoxObject) else self.b
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
            if isinstance(obj, BoxObject):
                obj._add_root(self)
                self._add_branch(obj)

    def __iter__(self):
        args = [obj if isinstance(obj, BoxObject)\
                else repeat(obj) for obj in self.args]
        for a, *args in zip(self.a, *args):
            yield self.selector(a, *args)

    def __next__(self):
        args = [next(obj) if isinstance(obj, BoxObject)\
                else obj for obj in self.args]
        return self.selector(next(self.a), *args)


class IfBox(AbstractBox):
    def __init__(self, cond, true, false):
        super().__init__()
        self.cond = cond
        self._check_fork(true, false)
        self.fork = (true, false)
        for obj in cond, true, false:
            if isinstance(obj, BoxObject):
                obj._add_root(self)
                self._add_branch(obj)

    def _check_fork(self, *fork):
        for b in fork:
            if isinstance(b, Outlet) or hasattr(b, '_outlets') and b._outlets:
                raise ValueError("true/false expressions can't contain outlets")

    def __iter__(self):
        true, false = [obj if isinstance(obj, BoxObject) else repeat(obj)\
                       for obj in self.fork]
        if isinstance(self.cond, BoxObject):
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
        cond = next(self.cond) if isinstance(self.cond, BoxObject)\
               else self.cond
        cond = int(not cond)
        if isinstance(self.fork[cond], BoxObject):
            return next(self.fork[cond])
        else:
            return self.fork[cond]


class ValueBox(AbstractBox):
    def __init__(self, value):
        super().__init__()
        self._value = value

    def __iter__(self):
        while True:
            yield self._value

    def __next__(self):
        return self._value


class SeqBox(AbstractBox):
    def __init__(self, lst):
        super().__init__()
        self._lst = lst
        self._len = len(lst)
        self._iterator = iter(lst)

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
            if isinstance(obj, BoxObject):
                obj._add_root(self)

    def __iter__(self):
        args = [obj if isinstance(obj, BoxObject) else repeat(obj)\
                for obj in self.args]
        kwargs = {
            key: value if isinstance(value, BoxObject) else repeat(value)\
                 for key, value in self.kwargs.items()}
        ...  # ?

    def __next__(self):
        args = [next(x) if isinstance(x, BoxObject) else x for x in self.args]
        kwargs = {
            key: next(value) if isinstance(value, BoxObject) else value\
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
