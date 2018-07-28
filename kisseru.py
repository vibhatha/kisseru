import ast
import functools
import logging
import inspect

from handler import HandlerContext
from handler import HandlerRegistry
from logger import LoggerEntry
from logger import LoggerExit
from func import ASTOps
from profiler import ProfilerEntry
from profiler import ProfilerExit
from passes import PassManager
from passes import PassContext
from passes import PassResult
from typed import TypeCheck
from transform import Transform
from stage import Stage
from tasks import gen_task
from tasks import TaskGraph
from tasks import PreProcess
from dot import DotGraphGenerator
from colors import Colors

xls = 'xls'
csv = 'csv'
png = 'png'

log = logging.getLogger(__name__)

# Setup kisseru logging
logging.basicConfig(level=logging.INFO)

# Setup kisseru handlers
prof_entry = ProfilerEntry("ProfilerEntry")
prof_exit = ProfilerExit("ProfilerExit")
logger_entry = LoggerEntry("LoggerEntry")
logger_exit = LoggerExit("LoggerExit")
ast_ops = ASTOps("ASTOps")

HandlerRegistry.register_init_handler(ast_ops)

HandlerRegistry.register_pre_handler(logger_entry)
HandlerRegistry.register_pre_handler(prof_entry)
HandlerRegistry.register_post_handler(prof_exit)
HandlerRegistry.register_post_handler(logger_exit)

# Setup graph IR passes
preprocess = PreProcess("Graph Preprocess")
type_check = TypeCheck("Type Check")
transform = Transform("Data Type Transformation")
stage = Stage("Stage Data")
dot_before = DotGraphGenerator("Dot Graph Generation", "before")
dot_after = DotGraphGenerator("Dot Graph Generation", "after")

PassManager.register_pass(preprocess)
PassManager.register_pass(dot_before)
PassManager.register_pass(type_check)
PassManager.register_pass(transform)
PassManager.register_pass(stage)
PassManager.register_pass(dot_after)

params = {'split': None}
_graph = TaskGraph()


def task(**configs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Run task init handlers
            ctx = HandlerContext(func)
            # We need to save the prototype meta data before we recompile the
            # function. This is due to the fact that 'compile' loses type
            # information for some reason. But we want to persist this
            # information through any recompilation which may happen as part of
            # the handlers since we need type information for later graph
            # compiler passes like TypeCheck
            ctx.sig = inspect.signature(func)
            for init in HandlerRegistry.init_handlers:
                init.run(ctx)

            global _graph
            task, tasklets = gen_task(ctx.fn, ctx.sig, args, kwargs)
            _graph.add_task(task)
            if tasklets == ():
                return task
            else:
                return tasklets

        return wrapper

    return decorator


def app(**configs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _graph.name = func.__name__
            print(Colors.OKRED +
                  "[KISSERU] Compiling pipeline {}".format(_graph.name) +
                  Colors.ENDC)
            print("========================================")
            print("")
            func(*args, **kwargs)
            return _graph

        log.info("Return app")
        return wrapper

    return decorator


class AppRunner(object):
    def __init__(self, app):
        self.app = app

    def run(self):
        # Get the task graph by running the app specification
        graph = self.app()

        # Now run the passes on the graph IR. PassContext holds any errors
        # encountered during the graph processing. We fail fast if we encounter
        # any errors during a pass.
        ctx = PassContext()
        for p in PassManager.passes:
            res = p.run(graph, ctx)
            if res == PassResult.ERROR:
                # [TODO] Print user friendly error message using the ctx
                # information here
                raise Exception("Aborting pipeline compilation due to errors")

        print("            .             ")
        print("            .             ")
        print(Colors.OKRED +
              "[Compiler] Successfully compiled the pipeline ...\n" +
              Colors.ENDC)

        # for tid, task in graph.tasks.items():
        # print("Dumping task {}".format(str(tid)))
        # task.dump()

        # Finally push the validated (and hopefully optimized) graph IR to
        # specified code generation backend or runner given we didn't encounter
        # any errors during the graph processing passes
        print("")
        print(Colors.OKBLUE +
              "[KISSERU] Running pipeline {}".format(_graph.name) +
              Colors.ENDC)
        print("========================================")
        print("")

        for tid, source in graph.sources.items():
            source.run()

        # Run any post code generation tasks which passes may run for
        # tearing down or saving computed results
        for p in PassManager.passes:
            res = p.post_run(graph, ctx)
