"""Shared test fixtures.

Pytest fixture docs:
https://docs.pytest.org/en/latest/fixture.html#conftest-py-sharing-fixture-functions
"""

import collections
import contextlib
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback

import pytest

import utils

# Set up logging
LOGGER = logging.getLogger("autograder")

# How long to wait for server in separate process to start or stop
TIMEOUT = 5

# Number of Workers which will run in separate processes
N_WORKERS = 3

# The mapreduce_client fixture will return a MapReduceClient object
MapReduceClient = collections.namedtuple(
    "MapReduceClient",
    [
        "manager_host",
        "manager_port",
    ],
)


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    """Print uncaught exceptions in child threads immediately.

    PROBLEM: An uncaught exception in a child thread kills that thread, but
    not the test.  The main thread may then wait forever for the dead thread,
    so the test hangs.  By default, pytest saves child thread exceptions and
    reports them as a warning only after the test finishes.  A hung test never
    finishes, so the student sees no error message at all.

    SOLUTION: Replace threading.excepthook, which Python calls when a child
    thread raises an uncaught exception.  Our hook prints the traceback to the
    terminal immediately, using the same format pytest uses for exceptions in
    the main thread.  The test may still hang, but now there's an error
    message explaining why.

    This is a pytest hook that runs once at configuration time.
    https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_configure

    GOTCHAS: Each of these was tried and doesn't work.

    1. Calling pytest.fail() in the hook doesn't stop the test.  The hook runs
       in the child thread, so pytest.fail() raises an exception in the child
       thread, not in the main thread where the test is running.

    2. Using LOGGER.critical() in the hook prints nothing unless the student
       runs pytest with --log-cli-level.  Pytest captures log messages and
       shows them only after a test fails, which never happens if it hangs.

    3. Printing to sys.stderr prints nothing, because pytest captures stdout
       and stderr during a test.  We temporarily disable capturing with the
       capture manager, the same way pytest's own live logging does.

    4. Disabling pytest's thread exception plugin with
       config.pluginmanager.set_blocked("threadexception") is too late from a
       conftest.py.  Pytest's plugin installs its own threading.excepthook
       after ours, overwriting it.  Instead, we use trylast=True to run after
       pytest's plugin, then wrap pytest's hook rather than replace it.

    5. Formatting the exception with pytest's ExceptionInfo shows frames from
       Python's threading library before the student's code.  We filter out
       those frames so the traceback starts at the student's thread function.
       We compare against the exact path of the threading module, so a
       student file that happens to be named threading.py isn't hidden.

    6. Pytest's terminal writer buffers its output when stdout isn't a
       terminal, for example when output is redirected to a file or in CI.  If
       the test hangs, the buffered traceback never appears.  We flush it.

    7. If our hook raises an exception, Python prints an error message to
       stderr, which pytest captures, so the student sees nothing.  We catch
       any exception, fall back to printing a plain traceback, and always
       call pytest's hook afterward.

    8. Two child threads can raise at the same time, for example the
       Manager's TCP and UDP threads.  Without a lock, their tracebacks
       interleave and both threads pause and resume capturing at once.

    """
    # Pytest's own hook, installed earlier by its threadexception plugin.
    # We'll call it after printing so that pytest still reports the warning
    # at the end of the test, as it normally would.
    prev_hook = threading.excepthook

    # One thread prints at a time.  See GOTCHA 8.
    print_lock = threading.Lock()

    def print_pytest_format(args):
        """Print exception in pytest format, bypassing pytest output capture."""
        # Wrap the exception so that pytest can format it
        excinfo = pytest.ExceptionInfo.from_exc_info(
            (args.exc_type, args.exc_value, args.exc_traceback)
        )

        # Remove frames from Python's threading library.  See GOTCHA 5.
        def tbfilter(excinfo):
            return excinfo.traceback.filter(
                lambda entry: str(entry.path) != threading.__file__
            )

        # Pause pytest's capturing of stdout and stderr so the traceback
        # reaches the terminal right away.  See GOTCHA 3.
        terminal = config.get_terminal_writer()
        capture_manager = config.pluginmanager.getplugin("capturemanager")
        with capture_manager.global_and_fixture_disabled():
            terminal.line()
            terminal.sep(
                "!",
                f"Uncaught exception in thread {args.thread.name}",
                red=True,
            )
            excinfo.getrepr(style="long", tbfilter=tbfilter).toterminal(terminal)

            # Flush now because the test may hang.  See GOTCHA 6.
            terminal.flush()

    def print_sys_exit_note(args):
        """Print a short note when a child thread calls sys.exit().

        Python's default hook ignores SystemExit.  In a child thread,
        sys.exit() stops only that thread, so a student who expects it to
        stop the program may cause a hang.  A short note explains the hang
        without a scary traceback when the test passes anyway.

        """
        terminal = config.get_terminal_writer()
        capture_manager = config.pluginmanager.getplugin("capturemanager")
        with capture_manager.global_and_fixture_disabled():
            terminal.line()
            terminal.line(
                f"Thread {args.thread.name} called sys.exit(), which stops "
                "only that thread, not the program.  See the Threads and "
                "Sockets tutorial for how to shut down threads: "
                "https://eecs485staff.github.io/p4-mapreduce/threads-sockets.html",
                yellow=True,
            )
            terminal.flush()

    def print_plain_format(args):
        """Print exception in Python's default format, bypassing capture."""
        capture_manager = config.pluginmanager.getplugin("capturemanager")
        if capture_manager is None:
            disabled = contextlib.nullcontext()
        else:
            disabled = capture_manager.global_and_fixture_disabled()
        with disabled:
            print("\nUncaught exception in child thread", file=sys.stderr)
            traceback.print_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                file=sys.stderr,
            )
            sys.stderr.flush()

    def thread_exception_hook(args):
        """Print exception immediately, then call pytest's hook.

        Python calls this function in the child thread that raised the
        exception.  The args parameter is a threading.ExceptHookArgs object.
        https://docs.python.org/3/library/threading.html#threading.excepthook

        """
        try:
            with print_lock:
                try:
                    if issubclass(args.exc_type, SystemExit):
                        print_sys_exit_note(args)
                    else:
                        print_pytest_format(args)
                except Exception:
                    # Our pretty printing failed.  See GOTCHA 7.
                    print_plain_format(args)
        finally:
            # Let pytest record the exception as usual.  See GOTCHA 4.
            prev_hook(args)

    # Configure threading library to call our hook
    threading.excepthook = thread_exception_hook


@pytest.fixture(name="mapreduce_client")
def setup_teardown_mapreduce_client():
    """Start a MapReduce Manager and Worker Servers in separate processes."""
    LOGGER.info("Setup test fixture 'mapreduce_client'")

    # Acquire open ports
    manager_port, *worker_ports = utils.get_open_port(nports=1 + N_WORKERS)

    # Match the server log level to the current log level.  For that we
    # need to access a protected member of the logging library.
    loglevel = logging._levelToName[logging.root.level]

    # Each server is a LiveServer object whose lifetime is automatically
    # managed by a context manager
    with contextlib.ExitStack() as stack:
        processes = []

        # Start Manager
        LOGGER.info("Starting Manager")
        process = stack.enter_context(
            subprocess.Popen(
                [
                    shutil.which("mapreduce-manager"),
                    "--port",
                    str(manager_port),
                    "--loglevel",
                    loglevel,
                ]
            )
        )
        processes.append(process)
        wait_for_server_ready(process, manager_port)

        # Start Workers
        for worker_port in worker_ports:
            LOGGER.info("Starting Worker")
            process = stack.enter_context(
                subprocess.Popen(
                    [
                        shutil.which("mapreduce-worker"),
                        "--port",
                        str(worker_port),
                        "--manager-port",
                        str(manager_port),
                        "--loglevel",
                        loglevel,
                    ]
                )
            )
            processes.append(process)
            wait_for_server_ready(process, worker_port)

        # Transfer control to test.  The code before the "yield" statement is
        # setup code, which is executed before the test.  Code after the
        # "yield" is teardown code, which is executed at the end of the test.
        # Teardown code is executed whether the test passed or failed.
        yield MapReduceClient("localhost", manager_port)

        # Send shutdown message
        utils.send_message({"message_type": "shutdown"}, port=manager_port)

        # Wait for processes to stop
        wait_for_process_all_stopped(processes)

        # Check for clean exit
        for process in processes:
            assert process.returncode == 0, f"{process} returncode={process.returncode}"

        # Kill servers
        LOGGER.info("Teardown test fixture 'mapreduce_client'")
        for process in processes:
            process.terminate()


def wait_for_server_ready(process, port):
    """Wait for server to respond, raise exception on timeout."""
    for _ in range(10 * TIMEOUT):
        if port_is_open("localhost", port):
            return
        if process.poll() is not None:
            raise ChildProcessError(f"Premature exit: {process}")
        time.sleep(0.1)
    raise ChildProcessError(f"Failed to start: {process}")


def port_is_open(host, port):
    """Return True if host:port is open."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect((host, port))
        except ConnectionRefusedError:
            return False
        return True


def wait_for_process_all_stopped(processes):
    """Return after all processes are not alive."""
    for _ in range(10 * TIMEOUT):
        if all(p.poll() is not None for p in processes):
            return
        time.sleep(0.1)
    raise ChildProcessError("Some processes failed to stop.")
