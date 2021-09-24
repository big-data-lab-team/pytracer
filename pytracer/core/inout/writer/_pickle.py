
import atexit
import datetime
import inspect
import io
import os
import pickle
import shutil
import threading
import traceback

import pytracer.core.inout._init as _init
import pytracer.utils as ptutils
from pytracer.core.config import config as cfg
from pytracer.core.config import constant
from pytracer.core.wrapper.cache import dumped_functions, visited_files
from pytracer.module.info import register
from pytracer.utils import get_functions_from_traceback, report
from pytracer.utils.log import get_logger

from . import _writer

logger = get_logger()

lock = threading.Lock()


def increment_visit(module, function):
    if (key := f"{module}.{function}") in dumped_functions:
        dumped_functions[key] += 1
    else:
        dumped_functions[key] = 1


class WriterPickle(_writer.Writer):

    elements = 0
    count_ofile = 0

    def __init__(self):
        self.parameters = _init.IOInitializer()
        self.datefmt = "%y%m%d%H%M%S"
        self._init_ostream()
        atexit.register(self.exit)

    def exit(self):
        # Be sure that all data in pickle buffer is dumped
        logger.debug("Close writer", caller=self)
        self.ostream.flush()
        self.ostream.close()
        if os.path.isfile(self.filename_path):
            if os.stat(self.filename_path).st_size == 0:
                os.remove(self.filename_path)
        self.copy_sources()

    def get_filename(self):
        return self.filename

    def get_filename_path(self):
        return self.filename_path

    def copy_sources(self):
        for filename in visited_files:
            src = filename
            if os.path.isfile(src):
                dst = f"{self.parameters.cache_sources_path}{os.path.sep}{filename}"
                dstdir = os.path.dirname(dst)
                os.makedirs(dstdir, exist_ok=True)
                shutil.copy(src, dst)

    def _init_streams(self):
        try:
            self.ostream = open(self.filename_path, "wb")
            self.pickler = pickle.Pickler(
                self.ostream, protocol=pickle.HIGHEST_PROTOCOL)
            self.pickler.fast = True
        except OSError as e:
            logger.error(f"Can't open pickle file: {self.filename_path}",
                         error=e, caller=self, raise_error=False)
        except Exception as e:
            logger.critical("Unexpected error", error=e, caller=self)

    def _init_ostream(self):
        filename = self.parameters.trace
        self.filename = ptutils.get_filename(
            filename, constant.extension.pickle)
        self.filename_path = self._get_filename_path(self.filename)

        self._init_streams()

    def _get_filename_path(self, filename):
        ptutils.check_extension(filename, constant.extension.pickle)
        filename, ext = os.path.splitext(filename)
        ext = ext if ext else constant.extension.pickle
        return (f"{self.parameters.cache_path}{os.sep}"
                f"{self.parameters.cache_traces}{os.sep}"
                f"{filename}{ext}")

    def is_looping(self):

        def aux(stack):
            return '/pytracer/core' in stack.filename and stack.function == 'write'
        return sum(map(aux, inspect.stack())) >= 2

    def is_writable(self, obj):
        if self.is_looping():
            return False
        try:
            pickle.dump(obj, io.BytesIO())
            return True
        except Exception as e:
            try:
                obj["args"] = {}
            except (AttributeError, KeyError, TypeError):
                pass
            logger.warning(
                f"Object is not writable: {obj}", caller=self, error=e)
            return False

    def _write(self, to_write):
        self.pickler.dump(to_write)

    def critical_writing_error(self, e):
        possible_functions = get_functions_from_traceback()
        msg = "Possible functions responsible for the issue:\n"
        msg += "\n".join([f"\t{f}" for f in possible_functions])
        msg += "\nTry again, excluding them\n"
        logger.critical(f"{msg}Unexpected error while writing",
                        error=e, caller=self)

    def clean_args(self, args):

        keys = list(args.keys())

        for name in keys:
            if name == 'self' or not self.is_writable(args[name]):
                args.pop(name)

        return args

    def write(self, **kwargs):
        function = kwargs["function"]
        time = kwargs["time"]
        module_name = kwargs["module_name"]
        function_name = kwargs["function_name"]
        label = kwargs["label"]
        args = kwargs["args"]
        backtrace = kwargs["backtrace"]

        increment_visit(module_name, function_name)

        args = self.clean_args(args)

        function_id = id(function)
        to_write = {"id": function_id,
                    "time": time,
                    "module": module_name,
                    "function": function_name,
                    "label": label,
                    "args": args,
                    "backtrace": backtrace}

        logger.debug((f"id: {function_id}\n"
                      f"time: {time}\n"
                      f"module: {module_name}\n"
                      f"function: {function_name}\n"
                      f"label: {label}\n"
                      f"backtrace: {backtrace}\n"), caller=self)

        if lock.locked():
            return
        lock.acquire()
        try:
            if not self.is_writable(to_write):
                to_write['args'] = {}

            if report.report.report_enable():
                key = (module_name, function_name)
                value = to_write
                report.report.report(key, value)

            if not report.report.report_only():
                self._write(to_write)

        except pickle.PicklingError as e:
            logger.error(
                f"while writing in Pickle file: {self.filename_path}",
                error=e, caller=self)
        except (AttributeError, TypeError) as e:
            logger.warning(
                f"Unable to pickle object: {args} {function_name}", caller=self, error=e)
            if report.report_enable():
                key = (module_name, function_name)
                value = to_write
                report.report(key, value)
            if not report.report_only():
                to_write['args'] = {}
                self._write(to_write)
        except Exception as e:
            logger.debug(f"Writing pickle object: {to_write}", caller=self)
            self.critical_writing_error(e)
        lock.release()

    def inputs(self, **kwargs):
        self.write(**kwargs, label="inputs")

    def module_name(self, obj):
        module = getattr(obj, "__module__", "")
        if not module and hasattr(module, "__class__"):
            module = getattr(obj.__class__, "__module__")
        return module

    def inputs_instance(self, **kwargs):
        function = kwargs.pop("instance")
        function_name = getattr(function, "__name__", "")
        module_name = self.module_name(function)
        self.write(**kwargs,
                   function=function,
                   function_name=function_name,
                   module_name=module_name,
                   label="inputs")

    def outputs(self, **kwargs):
        self.write(**kwargs, label="outputs")

    def outputs_instance(self, **kwargs):
        function = kwargs.pop("instance")
        function_name = getattr(function, "__name__", "")
        module_name = self.module_name(function)
        self.write(**kwargs,
                   function=function,
                   function_name=function_name,
                   module_name=module_name,
                   label="outputs")

    def backtrace(self):
        if cfg.io.backtrace:
            stack = traceback.extract_stack(limit=4)[0]
            visited_files.add(stack.filename)
            return stack
        return None
