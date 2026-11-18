from time import perf_counter
from functools import wraps


def timeit(function):
    """
    Decorator to print execution interval of callables in seconds.

    Example 1:
        >>> @timeit
        >>> def function_to_be_optimized(*args, **kwargs):
        >>>     return 'fuction result'
        >>> function_to_be_optimized()
        function_to_be_optimized took 4.31e-09 s
        'fuction result'

    Example 2:
        >>> from time import sleep
        >>> timeit(sleep)(3)
        sleep took 2.999 s
    """

    @wraps(function)
    def wrapper(*args, **kwargs):
        start = perf_counter()
        result = function(*args, **kwargs)
        end = perf_counter()
        interval = end - start
        print(f"{function.__name__} took {interval:0.4g} s")
        return result

    return wrapper


def addAttributes(**attributes):
    """
    Decorator to add attributes to callables (i.e., functions, methods or
    classes)

    Example:
        @addAttributes(context='maths', origin='geometry')
        def pi():
            return 3.14
        print(pi())  # -> 3.14
        print(pi.context)  # -> 'maths'
        print(pi.origin)  # -> 'geometry'
    """

    def _addAttributes(function):
        for key, val in attributes.items():
            setattr(function, key, val)
        return function

    return _addAttributes
