
from sc3.all import *  # *** BUG: No funciona si import sc3 no se inicializa.
from sc3.base.functions import AbstractFunction


# https://stackoverflow.com/questions/26927571/multiple-inheritance-in-python3-with-different-signatures
# https://stackoverflow.com/questions/45581901/are-sets-ordered-like-dicts-in-python3-6

# - Reemplazar call por next
# - Nombrar los un/bin/narops aunque sea an __str__
# - Los valores de repetición de los patterns podrían depender de una variable
#   de configuración que haga que sean infinitos o no (Pattern.repeat = True).


class BoxObject():
    __NOCACHE = object()

    def __init__(self):
        self.__cache = self.__NOCACHE
        self.__roots = []
        self.__outlets = []

    # *** EN VEZ DE CALLABLES PUEDEN SER ITERABLES... Y SE LLAMA CON next. SI SE CONSIDERAN COMO PATTERNS...
    def __call__(self):
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


class Patch():
    current_patch = None

    def __init__(self):
        self.tree = None  # *** puede haber más de un árbol independiente?
        # bangs es un mensage, no existe como objeto.
        # message queda fuera de tree (empuja)...
        self.messages = None
        self._previous_patch = None
        self._open = False

    def begin(self):  # *** ver casos begin/end es para build o edit (tienen tree, bangs o messages).
        if self._open:
            raise Exception('patch already open')
        self._open = True
        self._previous_patch = self.current_patch
        type(self).current_patch = self

    def end(self):
        if not self._open:
            raise Exception('patch is not open')
        if type(self).current_patch is not self:
            raise Exception('patch is not current_patch')
        self._open = False
        type(self).current_patch = self._previous_patch


# HAY QUE HACER LA LÓGICA DEL OUTLET PARA QUE FUNCIONE EL PATCH Y EL ÁRBOL (TIRAR Y EMPUJAR).
# PUEDE HABER DISTINTOS TIPOS DE OBJETOS QUE SEAN OUTLET, TIENE QUE HABER UA RAÍZ.
# *** UNA POSIBILIDAD ES QUE LOS MENSAJES SOLO ACTUALICEN EL ESTADO DE LOS OBJETOS ***
# *** LUEGO NO HAY BANGS COMO EN PD/MAX, HAY UN OUTLET QUE TIRA EL ESTADO DE LA CADENA ***
# *** POSIBILIDAD: EL OUTLET (LA RAÍZ DEL ÁRBOL DE EJECUCIÓN) SE EVALÚA CADA VEZ
# *** QUE ALGÚN NODO CAMBIA DE ESTADO (!), POR MENSAJE O POR TRIGGER, ESO ES ***
# *** SIMILAR A LA LÓGICA DE LOS PROXIES COMO ESTRUCTURAS QUE SE ACTUALIZAN, ***
# *** ES EL GRAFO QUE SE ACTUALIZA Y ES COMO SI FUERA UNA LLAMADA ***
# *** (luego pueden haber llamadas que actualicen y no activen el outlet, eso sería la relación bang/set) ***
# No olvidar, parte de la idea es que lo que se programa queda como grafo fijo,
# los objetos son los mismos que luego se pueden acceder individualmente, eso
# no se lleva bien y confunde con la dinámica del proxy que reevalúa todo.
# COMENTARIO VIEJO
#     # +++ EL PROBLEMA PRINCIPAL VA A SER LA ACTUALIZACIÓN DE OUTLET QUE TIENE
#     # +++ QUE SER DESPUÉS DE LOS TRIGGERS QUE HAYAN A CADA CILCO POR UNIDAD TEMPORAL.
class Outlet(BoxObject):
    def __init__(self, graph):
        super().__init__()
        self.graph = graph
        if not isinstance(graph, Outlet) and isinstance(self.graph, BoxObject):
            self.graph._add_outlet(self)  # *** ¿Este método debería ser solo de Outlet? Es quién llama, el único que puede saber?
        else:
            raise ValueError(
                f"'{type(graph).__class__}' is not a valid graph object")

    def __call__(self):
        return self.graph()


class Inlet(BoxObject):
    def __init__(self, value):
        self._value = value

    def __call__(self):
        if isinstance(self._value, BoxObject):
            return self._value()
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


class symbol(): ...  # se pueden interpretar como nombres de métodos, es escriben dentro de mensajes, pd tiene @property (el arroba+el símbolo y los parámetros).
class numdata(): ...  # int, float, etc.
class listdata(): ...
class signal(): ...
class struct(): ...


class AbstractBox(BoxObject, AbstractFunction):
    def __call__(self):
        raise NotImplementedError(
            f'callable interface not defined for {type(self).__name__}')

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
        if isinstance(self.a, BoxObject):
            self.a._add_root(self)

    def __call__(self):
        return self.selector(self.a())


class BinaryOpBox(AbstractBox):
    def __init__(self, selector, a, b):
        super().__init__()
        self.selector = selector
        self.a = a
        self.b = b
        if isinstance(self.a, BoxObject):
            self.a._add_root(self)
        if isinstance(self.b, BoxObject):
            self.b._add_root(self)

    def __call__(self):
        # se necesita algún tipo de función as_boxobject.
        if isinstance(self.a, BoxObject):
            a = self.a()
        else:
            a = self.a
        if isinstance(self.b, BoxObject):
            b = self.b()
        else:
            b = self.b
        return self.selector(a, b)


class NAryOpBox(AbstractBox):
    def __init__(self, selector, a, *args):
        super().__init__()
        self.selector = selector
        self.a = a
        self.args = args
        if isinstance(self.a, BoxObject):
            self.a._add_root(self)
        for x in self.args:
            if isinstance(x, BoxObject):
                x._add_root(self)

    def __call__(self):
        args = [x() if isinstance(x, BoxObject) else x for x in self.args]
        return self.selector(self.a(), *args)


class IfBox(AbstractBox):
    def __init__(self, cond, true, false):
        super().__init__()
        self.cond = cond
        self._check_branches(true, false)
        self.branches = (true, false)
        for x in (self.cond, *self.branches):
            if isinstance(x, BoxObject):
                x._add_root(self)

    def _check_branches(self, *branches):
        for b in branches:
            if isinstance(b, Outlet) or hasattr(b, '_outlets') and b._outlets:
                raise ValueError("true/false expressions can't contain outlets")

    def __call__(self):
        cond = self.cond() if isinstance(self.cond, BoxObject) else self.cond
        cond = int(not cond)
        if isinstance(self.branches[cond], BoxObject):
            return self.branches[cond]()
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

    def __call__(self):
        return self._value


class FunctionBox(AbstractBox):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        for x in self.args + tuple(self.kwargs.values()):
            if isinstance(x, BoxObject):
                x._add_root(self)

    def __call__(self):
        args = [x() if isinstance(x, BoxObject) else x for x in self.args]
        kwargs = {
            k: (v() if isinstance(x, BoxObject) else v)\
            for k, v in self.kwargs.items()}
        return (*args, kwargs)
