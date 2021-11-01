from abc import abstractmethod

from pytracer.utils.singleton import Singleton

from . import _wrapper


class Writer(metaclass=Singleton):

    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def get_filename(self):
        pass

    @abstractmethod
    def get_filename_path(self):
        pass

    @abstractmethod
    def write(self, **kwargs):
        pass

    @abstractmethod
    def inputs(self, **kwargs):
        pass

    @abstractmethod
    def outputs(self, **kwargs):
        pass

    @abstractmethod
    def backtrace(self):
        pass


# Writer.wrapper_function = _wrapper.wrapper_function
# Writer.wrapper_class = _wrapper.wrapper_class
# Writer.wrapper_instance = _wrapper.wrapper_instance
# Writer.wrapper_ufunc = _wrapper.wrapper_ufunc
