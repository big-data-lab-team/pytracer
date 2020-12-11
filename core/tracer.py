#!/usr/bin/python3

import argparse
import importlib.util
import inspect
import os
import sys
from importlib import invalidate_caches
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec

from pytracer.core.utils import str2bool
from pytracer.core.config import config as cfg
from pytracer.core.utils.log import get_logger
from pytracer.core.wrapper.wrapper import WrapperModule


logger = get_logger()


class Myloader(Loader):

    def __init__(self, fullname, path=None):
        self.fullname = fullname
        self.path = path
        self.visited_modules = set()

    def is_package(self, fullname):
        return True

    def find_spec(self, fullname, path=None):
        logger.debug(f"find spec {fullname} {path}", caller=self)
        return super().find_spec(fullname, path)

    def find_module(self, fullname, path=None):
        logger.debug(f"find spec {fullname} {path}", caller=self)
        spec = self.find_spec(fullname, path)
        if spec is None:
            return None
        return spec

    def compare_module(self, mod1, mod2):
        logger.debug(f"Comparing {mod1} and {mod2}")
        dir1 = dir(mod1)

        for attr in dir1:
            a1 = getattr(mod1, attr, None)
            a2 = getattr(mod2, attr, None)
            if a1 != a2:
                logger.debug(f"{a1} and {a2} differ", caller=self)
                if inspect.ismodule(a1):
                    self.compare_module(a1, a2)

    def sanitize_check(self, real_module, wrapped_module, indent=""):
        if wrapped_module.__name__ in self.visited_modules:
            return

        logger.debug(
            f"{indent}Sanitize check for module {wrapped_module}", caller=self)
        self.visited_modules.add(wrapped_module.__name__)
        name_wrp = wrapped_module.__name__
        symbols = dir(real_module)

        for sym in symbols:
            # Doing this instead of hasattr to not call __getattr__ of
            # the module since it makes an infinite loop for numpy.testing
            try:
                object.__getattribute__(real_module, sym)
                has_attr = True
            except AttributeError:
                has_attr = False
            if not has_attr:
                continue
            logger.debug(f"{indent+' '}checking symbol {sym}", caller=self)
            if not hasattr(wrapped_module, sym):
                if sym == "__warningregistry__":
                    logger.warning(
                        f"symbol {sym} is missing in the wrapped module {name_wrp}", caller=self)
                    continue
                else:
                    logger.error(
                        f"symbol {sym} is missing in the wrapped module {name_wrp}", caller=self)
            sym_obj_wrp = getattr(wrapped_module, sym)
            sym_obj_rl = getattr(real_module, sym)
            if inspect.ismodule(sym_obj_wrp):
                self.sanitize_check(sym_obj_rl, sym_obj_wrp, indent+" ")
        logger.debug(
            f"Sanitize check for module {wrapped_module} done", caller=self)

    def create_module(self, spec):
        try:
            logger.debug(f"create module for spec {spec}")
            real_spec = importlib.util.find_spec(spec.name)
            real_module = importlib.util.module_from_spec(real_spec)
            real_spec.loader.exec_module(real_module)
            wrp = WrapperModule(real_module)
            wrp.assert_lazy_modules_loaded()
            wrp.assert_lazy_attributes_are_initialized()
            wrapped_module = wrp.get_wrapped_module()
            self.sanitize_check(real_module, wrapped_module)
            logger.debug(
                f"wrapper module for {spec.name} created", caller=self)
            return wrapped_module
        except Exception as e:
            logger.critical("Unknown exception", error=e, caller=self)

    def exec_module(self, module):
        try:
            _ = sys.modules.pop(module.__name__)
        except KeyError:
            logger.debug(
                f"module {module.__name__} is not in sys.modules", caller=self)

        sys.modules[module.__name__] = module
        globals()[module.__name__] = module

        parent = module.__name__.rpartition(".")[0]
        while parent:
            logger.debug(f"exec_module {module.__name__} -> {parent}")
            if parent not in sys.modules:
                logger.debug(f"not in sys.modules :{parent}", caller=self)
                parent_module = importlib.import_module(parent)
                sys.modules[parent] = parent_module
                globals()[parent] = parent_module
            else:
                parent_module = sys.modules[parent]
            setattr(module, parent, parent_module)
            parent = parent.rpartition(".")[0]


class MyImporter(MetaPathFinder):

    modules_to_load = list()

    def __init__(self):
        self._get_modules_to_load()

    def _get_modules_to_load(self):
        if self.modules_to_load == []:
            for module in cfg.modules_to_load:
                module_name = module.strip()
                logger.debug(f"module to load {module_name}", caller=self)
                try:
                    _ = sys.modules.pop(module_name)
                except KeyError:
                    logger.debug(
                        f"no module {module_name} in sys.modules", caller=self)
                self.modules_to_load.append(module_name)

    def find_spec(self, fullname, path=None, target=None):
        to_load = False
        for module in self.modules_to_load:
            if fullname.startswith(module):
                to_load = True
        if not to_load:
            return None

        logger.debug(f"find spec for {fullname} {path} {target}", caller=self)
        # if we are in the create_module function,
        # we return the real module (return None)
        for stack in inspect.stack():
            if stack.filename.endswith(__file__) and \
                    stack.function == "create_module":
                logger.debug(f"We are in {__file__}")
                return None

        spec = ModuleSpec(fullname, Myloader(fullname))

        logger.debug(f"{fullname} spec found", caller=self)
        return spec


def install(loader):
    # insert the path hook ahead of other path hooks
    sys.meta_path.insert(0, loader)
    # clear any loaders that might already be in use by the FileFinder
    sys.path_importer_cache.clear()
    invalidate_caches()


def run():
    if sys.platform != "linux":
        logger.error("Other platform than linux not supported")

    finder = MyImporter()
    install(finder)
    for module in finder.modules_to_load:
        if module in sys.modules:
            logger.debug(
                f"original module {module} was removed from sys.module")
            sys.modules.pop(module)
        logger.debug(f"load module {module}")
        importlib.import_module(module)


def exec_module(module_name, extra_args):
    spec = importlib.util.spec_from_file_location("__main__", module_name)
    module = importlib.util.module_from_spec(spec)
    # Pass arguments to program
    argindex = sys.argv.index(module_name)
    sys.argv = sys.argv[argindex:]
    spec.loader.exec_module(module)


def main(args, extra_args):

    if os.path.isfile(args.module):
        if not args.dry_run:
            run()
        exec_module(args.module, extra_args)
    else:
        logger.error(f"File {args.module} not found")


def init_arguments(parser):
    parser.add_argument("--module", required=True,
                        help="path of the module to trace")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the module wihtout tracing it")


def init_module(subparser, pytracer_modules):
    tracer_parser = subparser.add_parser("trace", help="trace functions")
    init_arguments(tracer_parser)
    pytracer_modules["trace"] = main


if __name__ == "__main__":
    parser_args = argparse.ArgumentParser(
        description="Pytracer tracing module")
    init_arguments(parser_args)
    args = parser_args.parse_args()
    main(args)
