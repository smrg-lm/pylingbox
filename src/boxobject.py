
from abc import ABC, abstractmethod

from sc3.all import *  # *** BUG: No funciona si import sc3 no se inicializa.
from sc3.base.functions import AbstractFunction


# https://stackoverflow.com/questions/26927571/multiple-inheritance-in-python3-with-different-signatures
# https://stackoverflow.com/questions/45581901/are-sets-ordered-like-dicts-in-python3-6

# - Nombrar los un/bin/narops aunque sea an __str__
# - Los valores de repetición de los patterns podrían depender de una variable
#   de configuración que haga que sean infinitos o no (Pattern.repeat = True).

# - CONTINUAR DESDE: PENSAR CÓMO TIENEN QUE FUNCIONAR LOS TRIGGERS.
# - Pensar simplemente como lenguaje para la secuenciación en vez de Pbind.
# - Lo importante son los triggers con diferente tempo para las variables.
# - Los outlets pueden ser genéricos o el equivalente a los streams de eventos
#   (pbind), esta interfaz es más bien funcional en vez de declarativa.
# - Las synthdef, como funciones que se llama, podrían ser outlets, distintos
#   tipos de outlets podrían generar distintos timpos de streams de eventos
#   que creen o no synths, como reemplazo de pbind/pmono/artic.
# - Tal vez mejor no hacer mensajes, descartar la idea de las cajas es adoptar
#   el paradigma más funcional.


# Para triggers:
class TimeFunction(ABC):
    @abstractmethod
    def _iter_value(self):
        pass

    @abstractmethod
    def _iter_map(self):
        pass

    def __iter__(self):
        if isinstance(self.pattern, TimeFunction):
            return self._iter_map()
        else:
            return self._iter_value()

    def __len__(self):
        return len(self.pattern)


class Within(TimeFunction):
    def __init__(self, time, pattern):
        self.unit = time
        self.delta = time / len(pattern)
        self.pattern = pattern

    def _iter_value(self):
        for value in self.pattern:
            yield (self.delta, value)

    def _iter_map(self):
        # within comprime o expande temporalmente la salida de every.
        # n every d within t (cambia la proporción, nada más, pero
        # no era eso lo que pensé primero).
        for i in iter(self.pattern):
            scale = self.unit / self.pattern.unit
            yield (i[0] * scale, i[1])


class Every(TimeFunction):
    def __init__(self, time, pattern):
        self.unit = time * len(pattern)
        self.delta = time
        self.pattern = pattern

    def _iter_value(self):
        for value in self.pattern:
            yield (self.delta, value)

    def _iter_map(self):
        # every es resampleo/decimación de la salida de within,
        # son algoritmos de resampling para arriba o abajo pero lazy.
        # n within t every d.
        new_delta = self.delta
        new_count = 0
        old_count = 0
        for i in iter(self.pattern):
            old_delta = i[0]
            if new_count >= old_count + old_delta:
                old_count += old_delta
                continue
            if old_delta <= new_delta:
                yield (new_delta, i[1])
                new_count += new_delta
                old_count += old_delta
            else:
                old_count += old_delta
                while new_count < old_count\
                and new_count < self.pattern.unit - new_delta:
                    yield (new_delta, i[1])
                    new_count += new_delta

'''
print( list(Within(1, range(3))) )
print( list(Every(0.1, range(3))) )
print( list(Every(0.1, Within(1, range(3)))) )
print( list(Within(4, Every(0.5, range(3)))) )
'''


class BoxObject():
    __NOCACHE = object()

    def __init__(self):
        self.__cache = self.__NOCACHE
        self.__roots = []
        self.__outlets = []
        self.__triggers = []

    def __next__(self):
        return None

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
            r._clear_cache()

    def _add_root(self, value):
        if not value in self.__roots:
            self.__roots.append(value)

    def _remove_root(self, value):
        if value in self.__roots:
            self.__roots.remove(value)

    @property
    def _roots(self):
        return self.__roots

    def _add_outlet(self, value):
        if not value in self.__outlets:
            self.__outlets.append(value)

    def _remove_outlet(self, value):
        if value in self.__outlets:
            self.__outlets.remove(value)

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


class Patch():  # si distintos patch llaman tiran del árbol por medio de los outlets
    current_patch = None

    def __init__(self):
        # self.tree = None  # *** puede haber más de un árbol independiente?
        self._outlets = []
        self._triggers = []

    def _build(self):
        # Que los outlets y los triggers tengan fuente y destino.
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


class Outlet(BoxObject):
    def __init__(self, graph):
        super().__init__()
        self.graph = graph
        if not isinstance(graph, Outlet) and isinstance(self.graph, BoxObject):
            self.graph._add_outlet(self)  # *** ¿Este método debería ser solo de Outlet? Es quién llama, el único que puede saber?
        else:
            raise ValueError(
                f"'{type(graph).__class__}' is not a valid graph object")
        # Patch.current_patch._outlets.append(self)

    def __next__(self):
        return next(self.graph)


class Inlet(BoxObject):
    def __init__(self, value):
        self._value = value

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
    def __next__(self):
        raise NotImplementedError(
            f'generator interface not defined for {type(self).__name__}')

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
        self.a._add_root(self)
        # if isinstance(self.a, BoxObject):
        #     self.a._add_root(self)

    def __next__(self):
        # a = next(self.a) if isinstance(self.a, BoxObject) else self.a
        # return self.selector(a)
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

    def __next__(self):
        # se necesita algún tipo de función as_boxobject.
        a = next(self.a) if isinstance(self.a, BoxObject) else self.a
        b = next(self.b) if isinstance(self.b, BoxObject) else self.b
        return self.selector(a, b)


class NAryOpBox(AbstractBox):
    def __init__(self, selector, a, *args):
        super().__init__()
        self.selector = selector
        self.a = a
        self.args = args
        # for obj in (a, *args):
        for obj in args:
            if isinstance(obj, BoxObject):
                obj._add_root(self)

    def __next__(self):
        # a = next(self.a) if isinstance(self.a, BoxObject) else self.a
        args = [next(obj) if isinstance(obj, BoxObject)\
                else obj for obj in self.args]
        # return self.selector(a, *args)
        return self.selector(next(self.a), *args)


class IfBox(AbstractBox):
    def __init__(self, cond, true, false):
        super().__init__()
        self.cond = cond
        self._check_branches(true, false)
        self.branches = (true, false)
        for x in cond, true, false:
            if isinstance(x, BoxObject):
                x._add_root(self)

    def _check_branches(self, *branches):
        for b in branches:
            if isinstance(b, Outlet) or hasattr(b, '_outlets') and b._outlets:
                raise ValueError("true/false expressions can't contain outlets")

    def __next__(self):
        cond = next(self.cond) if isinstance(self.cond, BoxObject) else self.cond
        cond = int(not cond)
        if isinstance(self.branches[cond], BoxObject):
            return next(self.branches[cond])
        else:
            return self.branches[cond]
        # Acá está el quid de la cuestión, qué hace cuando no hace nada,
        # porque el if puede ser un disparador o encausador de flujo
        # que evalúa o no una parte del grafo (ifbox es quién va al outlet).
        # Max/Pd lo hacen mucho más simple, devuelve 1 o 0, pero eso
        # puede generar un bang que activa algo (el valor se genera empujando).
        # En este caso, esto es equivalente a integrar las estructuras de
        # control con las operaciones matemáticas. Como tanto la condición
        # como las posibles ramas tienen root en self los grafos if/else son
        # opcionales y están contenidos dentro de IfBox. El problema es que
        # gráficamente esto no se puede representar bien, poruqe los grafos
        # opcionales son parámetros de la caja, en vez de activarse según la
        # salida, y es la caja quién se conecta como flujo a lo que sigue.
        # Pero esto es lo que lo hace atractivo como lenguaje de control
        # alternativo a los patterns (!).
        # ----------------------------------------------------------------------
        # Pero veo un problema que hay que definir. Si el subpatch de las ramas
        # pueden contener outlets se complica, porque los outlets son los que
        # que evalúan, entonces no deberían poder haber outlets dentro del if
        # porque este sería (el if) el nodo raíz... además, es más complicada
        # la lógica si el outlet tiene que saber si está dentro de un if.
        # ----------------------------------------------------------------------
        # Claro, este es un if que filtra la entrada, como con las señales, en
        # vez de decidir qué camino seguir a la salida, ahora que me doy cuenta.
        # Es un select.
        # ----------------------------------------------------------------------


class ValueBox(AbstractBox):
    def __init__(self, value):
        super().__init__()
        self._value = value

    def __next__(self):
        return self._value


class FunctionBox(AbstractBox):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        for obj in (*args, *kwargs.values()):
            if isinstance(obj, BoxObject):
                obj._add_root(self)

    def __next__(self):
        args = [next(x) if isinstance(x, BoxObject) else x for x in self.args]
        kwargs = {
            k: (next(v) if isinstance(x, BoxObject) else v)\
            for k, v in self.kwargs.items()}
        return (*args, kwargs)

'''
a = ValueBox(1)
b = ValueBox(2)
c = a + b
o = Outlet(c)
next(o)
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
print(next(o))
b._value = 2
print(next(o))
'''
