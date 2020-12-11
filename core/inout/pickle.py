import atexit
import datetime
import io
import os
import pickle
import traceback
from collections import namedtuple
import numpy as np
import tables
import sys

import pytracer.core.inout as ptinout
import pytracer.core.utils as ptutils
from pytracer.core.utils.log import get_logger
from pytracer.core.config import constant, config as cfg
from pytracer.core.utils.singleton import Singleton


BacktraceDict = namedtuple(typename="BacktraceDict",
                           field_names=["filename",
                                        "line",
                                        "lineno",
                                        "locals",
                                        "name"])

logger = get_logger()


def split_filename(filename):
    _, name = os.path.split(filename)
    head, count, ext = name.split(os.extsep)
    return (head, count, ext)


def handle_not_pickle_serializable(args):
    if isinstance(args, float):
        return float(args)
    return str(args)


class Writer(metaclass=Singleton):

    elements = 0
    count_ofile = 0
    wrapper = ptinout.wrapper
    wrapper_class = ptinout.wrapper_class
    wrapper_instance = ptinout.wrapper_instance
    wrapper_ufunc = ptinout.wrapper_ufunc

    def __init__(self):
        self.parameters = ptinout.IOInitializer()
        self.datefmt = "%y%m%d%H%M%S"
        self._init_ostream()
        atexit.register(self.exit)

    def exit(self):
        # Be sure that all data in pickle buffer is dumped
        logger.debug("Close writer", caller=self)
        self.ostream.flush()
        self.ostream.close()
        if os.path.isfile(self.filename):
            if os.stat(self.filename).st_size == 0:
                os.remove(self.filename)

    def _init_ostream(self):
        if self.parameters.filename:
            self.filename = self.get_filename_path(
                self.parameters.filename)
        else:
            now = datetime.datetime.now().strftime(self.datefmt)
            filename = f"{now}{constant.pickle_ext}"
            self.filename = self.get_filename_path(filename)

        try:
            if hasattr(self, "ostream"):
                self.ostream.close()
            self.ostream = open(self.filename, "wb")
            self.pickler = pickle.Pickler(
                self.ostream, protocol=pickle.HIGHEST_PROTOCOL)
            self.count_ofile += 1
        except OSError as e:
            logger.error(f"Can't open Pickle file: {self.filename}",
                         error=e, caller=self)
        except Exception as e:
            logger.critical("Unexpected error", error=e, caller=self)

    def get_filename_path(self, filename):
        ptutils.check_extension(filename, constant.pickle_ext)
        filename, ext = os.path.splitext(filename)
        ext = ext if ext else constant.pickle_ext
        return (f"{self.parameters.cache_path}{os.sep}"
                f"{self.parameters.cache_traces}{os.sep}"
                f"{filename}{os.extsep}"
                f"{self.count_ofile}{ext}")

    def is_writable(self, obj):
        try:
            pickler_test = pickle.Pickler(io.BytesIO())
            pickler_test.dump(obj)
            return True
        except Exception as e:
            logger.warning(
                f"Object is not writable: {obj}", caller=self, error=e)
            return False

    def _write(self, to_write):
        self.pickler.dump(to_write)

    def write(self, **kwargs):
        function = kwargs["function"]
        time = kwargs["time"]
        module_name = kwargs["module_name"]
        function_name = kwargs["function_name"]
        label = kwargs["label"]
        args = kwargs["args"]
        backtrace = kwargs["backtrace"]

        function_id = id(function)
        to_write = {"id": function_id,
                    "time": time,
                    "module": module_name,
                    "function": function_name,
                    "label": label,
                    "args": args,
                    "backtrace": backtrace}
        try:
            if self.is_writable(to_write):
                self._write(to_write)

        except pickle.PicklingError as e:
            logger.error(
                f"while writing in Pickle file: {self.filename}",
                error=e, caller=self)
        except (AttributeError, TypeError):
            logger.warning(f"Unable to pickle object: {args}", caller=self)
        except Exception as e:
            logger.debug(f"Writing pickle object: {to_write}", caller=self)
            logger.critical("Unexpected error while writing",
                            error=e, caller=self)

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
            return stack
        return None


class Reader(metaclass=Singleton):

    def __init__(self):
        self.parameters = ptinout.IOInitializer()

    def read(self, filename):
        try:
            ptutils.check_extension(filename, constant.pickle_ext)
            logger.debug(f"Opening {filename}", caller=self)
            fi = open(filename, "rb")
            unpickler = pickle.Unpickler(fi)
            data = []
            while True:
                try:
                    _obj = unpickler.load()
                    data.append(_obj)
                except EOFError:
                    break
                except Exception as e:
                    logger.critical("[self.__name__] Unknown exception",
                                    error=e, caller=self)
            return data
        except OSError as e:
            logger.error(f"[self.__name__] Can't open Pickle file: {filename}",
                         error=e, caller=self)
        except pickle.PicklingError as e:
            logger.error(f"[self.__name__] While reading Pickle file: {filename}",
                         error=e, caller=self)
        except Exception as e:
            logger.critical("[self.__name__] Unexpected error",
                            error=e, caller=self)


class ExportDescription(tables.IsDescription):
    id = tables.UInt64Col()
    label = tables.StringCol(16)
    name = tables.StringCol(128)
    time = tables.UInt64Col()
    mean = tables.Float64Col()
    std = tables.Float64Col()
    sig = tables.Float64Col()

    class BacktraceDescription(tables.IsDescription):
        filename = tables.StringCol(1024)
        line = tables.StringCol(1024)
        lineno = tables.IntCol()
        name = tables.StringCol(128)


class Exporter(Writer, metaclass=Singleton):

    id_to_times = dict()

    def __init__(self):
        self.parameters = ptinout.IOInitializer()
        self._init_ostream()
        atexit.register(self.end)

    def _init_ostream(self):
        if self.parameters.export.dat:
            self.filename = self.get_filename_path(
                self.parameters.export.dat)
        else:
            self.filename = self.get_filename_path(constant.export.dat)

        if self.parameters.export.header:
            self.filename_header = self.get_filename_path(
                self.parameters.export.header)
        else:
            self.filename_header = self.get_filename_path(
                constant.export.header)

        # Pickler used to test if an object is dumpable
        if not hasattr(self, "_pickler_test"):
            self._pickler_test = pickle.Pickler(io.BytesIO())

        self.h5file = tables.open_file("test.h5", mode="w")

        try:
            if hasattr(self, "ostream"):
                self.ostream.close()
            self.ostream = open(self.filename, "wb")
            self.pickler = pickle.Pickler(
                self.ostream, protocol=pickle.HIGHEST_PROTOCOL)
            self.count_ofile += 1
        except OSError as e:
            logger.error(f"Can't open Pickle file: {self.filename}",
                         error=e, caller=self)
        except Exception as e:
            logger.critical("Unexpected error", error=e, caller=self)

    def get_filename_path(self, filename):
        ptutils.check_extension(filename, constant.pickle_ext)
        filename, ext = os.path.splitext(filename)
        ext = ext if ext else constant.pickle_ext
        return (f"{self.parameters.cache_path}{os.sep}"
                f"{self.parameters.cache_stats}{os.sep}"
                f"{filename}{os.extsep}"
                f"{self.count_ofile}{ext}")

    def end(self):
        self._dump_register()
        self.ostream.flush()
        self.ostream.close()
        self.h5file.close()

    def _dump_register(self):
        try:
            fo = open(self.filename_header, "wb")
            pickler = pickle.Pickler(fo, protocol=pickle.HIGHEST_PROTOCOL)
            pickler.dump(Exporter.id_to_times)
            fo.flush()
            fo.close()
        except Exception as e:
            raise e

    def backtrace_to_dict(self, backtrace):
        return BacktraceDict(filename=backtrace.filename,
                             line=backtrace.line,
                             lineno=backtrace.lineno,
                             name=backtrace.name)

    def _register_obj(self, obj):
        try:
            function_id = obj["id"]
            if function_id in Exporter.id_to_times:
                time = obj["time"]
                backtrace = self.backtrace_to_dict(obj["backtrace"])
                bt_to_time = Exporter.id_to_times[function_id]["backtrace"]
                if backtrace in bt_to_time:
                    bt_to_time[backtrace].add(time)
                else:
                    bt_to_time[backtrace] = set([time])
            else:
                backtrace = self.backtrace_to_dict(obj["backtrace"])
                bt_to_time = {backtrace: set([obj["time"]])}
                new_registration = {"name": obj["function"],
                                    "module": obj["module"],
                                    "backtrace": bt_to_time}
                Exporter.id_to_times[function_id] = new_registration
        except Exception as e:
            logger.error(
                f"Cannot registered object {obj}", error=e, caller=self)

    def export_arg(self, *args, **kwargs):

        row = kwargs["row"]
        stats = kwargs["stats"]
        function_id = kwargs["function_id"]
        label = kwargs["label"]
        name = kwargs["name"]
        time = kwargs["time"]
        backtrace = kwargs["backtrace"]
        function_grp = kwargs["hdf5_function_group"]

        ndim = stats.ndim()

        raw_mean = stats.mean()
        raw_std = stats.std()
        raw_sig = stats.sig()

        if ndim == 0:
            mean = raw_mean
            std = raw_std
            sig = raw_sig
        else:
            mean = np.mean(raw_mean, dtype=np.float64)
            std = np.mean(raw_std, dtype=np.float64)
            sig = np.mean(raw_sig, dtype=np.float64)

        row["id"] = function_id
        row["label"] = label
        row["name"] = name
        row["time"] = time
        row["mean"] = mean
        row["std"] = std
        row["sig"] = sig
        row["BacktraceDescription/filename"] = backtrace.filename
        row["BacktraceDescription/line"] = backtrace.line
        row["BacktraceDescription/lineno"] = backtrace.lineno
        row["BacktraceDescription/name"] = backtrace.name
        row.append()
        # We create array to keep the object
        if ndim > 0:
            filters = tables.Filters(complevel=9, complib='zlib')
            unique_id = "_".join([label, name, str(time)])
            atom_type = tables.Atom.from_dtype(stats.dtype())
            shape = stats.shape()
            mean_array = self.h5file.create_carray(
                function_grp, unique_id + "_mean",
                atom=atom_type, shape=shape, filters=filters)
            mean_array[:] = raw_mean

            std_array = self.h5file.create_carray(
                function_grp, unique_id + "_std",
                atom=atom_type, shape=shape, filters=filters)
            std_array[:] = raw_std

            sig_array = self.h5file.create_carray(
                function_grp, unique_id + "_sig",
                atom=atom_type, shape=shape, filters=filters)
            sig_array[:] = raw_sig

    def export(self, obj):
        module = obj["module"].replace(".", "_")
        function = obj["function"].replace(".", "_")
        label = obj["label"]
        args = obj["args"]
        backtrace = obj["backtrace"]
        function_id = obj["id"]
        time = obj["time"]
        module_grp_name = f"/{module}"
        if module_grp_name in self.h5file:
            module_grp = self.h5file.get_node(module_grp_name)
        else:
            module_grp = self.h5file.create_group("/", module)

        if function in module_grp:
            function_grp = module_grp[function]
            table = function_grp["values"]
        else:
            function_grp = self.h5file.create_group(module_grp, function)
            table = self.h5file.create_table(
                function_grp, "values", description=ExportDescription)
        row = table.row
        for name, stats in args.items():

            if isinstance(stats, list):
                for i, stat in enumerate(stats):
                    self.export_arg(row=row,
                                    stats=stat,
                                    function_id=function_id,
                                    label=label,
                                    name=f"{name}_TID{i}",
                                    time=time,
                                    backtrace=backtrace,
                                    hdf5_function_group=function_grp)

            else:
                self.export_arg(row=row,
                                stats=stats,
                                function_id=function_id,
                                label=label,
                                name=name,
                                time=time,
                                backtrace=backtrace,
                                hdf5_function_group=function_grp)

            table.flush()
        self.h5file.flush()