#!/usr/bin/env python3
"""Linux: python3 minimal.py [path/to/pcmanfm-qt]. Keep results in a new folder here."""
import ctypes
import os
from pathlib import Path
import shutil
import signal
import subprocess as sp
import sys
import tempfile
import time

NAME = "org.pcmanfm.PCManFM"
ROOT = None
PARENT = os.getpid()
LIBC = ctypes.CDLL(None, use_errno=True)


def stop(signum, frame):
    raise InterruptedError(f"stopped by signal {signum}")


def child():
    # End direct children even if the probe is killed; permit same-user gdb under Yama.
    if LIBC.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        os._exit(125)
    if os.getppid() != PARENT:
        os._exit(125)
    LIBC.prctl(0x59616D61, ctypes.c_ulong(-1), 0, 0, 0)  # PR_SET_PTRACER_ANY


def run(args, timeout=2):
    return sp.run(args, text=True, stdout=sp.PIPE, stderr=sp.STDOUT,
                  timeout=timeout, preexec_fn=child)


def bus(destination, path, method, *args):
    return run(["dbus-send", "--session", "--print-reply", "--reply-timeout=500",
                f"--dest={destination}", path, method, *args])


def backtrace(pid):
    path = ROOT / "backtrace.txt"
    print(f"Backtrace: {path}", flush=True)
    with path.open("w+") as trace:
        status, code = "gdb did not complete", None
        try:
            code = sp.run(["gdb", "-batch", "-iex", "set debuginfod enabled on",
                           "-iex", "set auto-solib-add off", "-p", str(pid),
                           "-ex", "sharedlibrary libgio-2.0", "-ex", "sharedlibrary libfm-qt",
                           "-ex", "set debuginfod enabled off", "-ex", "sharedlibrary",
                           "-ex", "thread apply all bt"], stdout=trace, stderr=sp.STDOUT,
                          timeout=90, preexec_fn=child).returncode
            status = f"gdb exit: {code}"
        except sp.TimeoutExpired:
            status = "gdb timed out after 90 seconds"
        finally:
            trace.write(f"\n{status}\n")
            trace.flush()
        trace.seek(0)
        return 2 if code == 0 and "Thread " in trace.read() else 3


def probe(binary):
    signal.alarm(180)  # Independent of the invoking launcher's lifetime.
    (ROOT / "probe.pid").write_text(str(os.getpid()))
    workers = []
    try:
        for _ in range(2):
            workers.append(sp.Popen([sys.executable, "-c", "while True: pass"], preexec_fn=child))
        for attempt in range(1, 41):
            home = ROOT / f"home-{attempt}"
            (home / "Desktop").mkdir(parents=True)
            env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                   "XDG_CACHE_HOME": str(home / ".cache"), "XDG_DATA_HOME": str(home / ".local/share")}
            with (ROOT / f"start-{attempt}.log").open("w") as log:
                process = sp.Popen([binary, "--desktop"], env=env, stdout=log,
                                   stderr=sp.STDOUT, preexec_fn=child)
                try:
                    end = time.monotonic() + 15
                    while True:
                        if process.poll() is not None:
                            print(Path(log.name).read_text(), file=sys.stderr, flush=True)
                            raise RuntimeError(f"application exited {process.returncode}; see {log.name}")
                        answer = bus(NAME, "/Application", "org.freedesktop.DBus.Introspectable.Introspect")
                        tree = run(["xwininfo", "-root", "-tree"])
                        window = "pcmanfm-desktop" in tree.stdout
                        if answer.returncode == 0 and tree.returncode == 0 and window:
                            print(f"start {attempt}: responsive", flush=True)
                            break
                        if time.monotonic() >= end:
                            owner = bus("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                        "org.freedesktop.DBus.GetConnectionUnixProcessID", f"string:{NAME}")
                            if owner.returncode != 0 or owner.stdout.split()[-1:] != [str(process.pid)]:
                                raise RuntimeError("startup failed; the launched process does not own its bus name")
                            print(f"start {attempt}: NOT READY; D-Bus={answer.returncode}, desktop={window}", flush=True)
                            return backtrace(process.pid)
                        time.sleep(0.1)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
        print("40 responsive starts; no hang observed in this run.", flush=True)
        return 0
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.wait()


def main():
    global ROOT
    if sys.platform != "linux":
        raise RuntimeError("run this script on Linux")
    for name in ["xvfb-run", "Xvfb", "xauth", "dbus-run-session", "dbus-send", "xwininfo", "gdb"]:
        if not shutil.which(name):
            raise RuntimeError(f"missing dependency: {name}")
    binary = shutil.which(sys.argv[1] if len(sys.argv) > 1 else "pcmanfm-qt")
    if not binary:
        raise RuntimeError("pcmanfm-qt binary not found")
    binary = str(Path(binary).resolve())
    if os.environ.get("PCMANFM_REPRO_PROBE") == "1":
        ROOT = Path(os.environ["PCMANFM_REPRO_ROOT"])
        return probe(binary)
    ROOT = Path(tempfile.mkdtemp(prefix="pcmanfm-repro-", dir=Path.cwd())).resolve()
    for name in ["tmp", "runtime", "config", "cache", "data"]:
        (ROOT / name).mkdir(mode=0o700)
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "LANG", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "DEBUGINFOD_URLS"}}
    env.update(HOME=str(ROOT), TMPDIR=str(ROOT / "tmp"), XDG_RUNTIME_DIR=str(ROOT / "runtime"),
               XDG_CONFIG_HOME=str(ROOT / "config"), XDG_CACHE_HOME=str(ROOT / "cache"),
               XDG_DATA_HOME=str(ROOT / "data"), QT_QPA_PLATFORM="xcb", XDG_SESSION_TYPE="x11",
               PCMANFM_REPRO_PROBE="1", PCMANFM_REPRO_ROOT=str(ROOT))
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    print(f"Results: {ROOT}\nCPU {cpu}: two busy workers; up to 40 starts; 180-second probe limit.", flush=True)
    command = ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24 -noreset -nolisten tcp",
               "dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()), binary]
    process = sp.Popen(command, env=env, cwd=ROOT, start_new_session=True)
    try:
        signal.alarm(200)
        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
    finally:
        # Keep the direct child unreaped until signalling: its PID pins this owned group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    signal.alarm(0)
    return process.returncode


if __name__ == "__main__":
    for signum in [signal.SIGALRM, signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
        signal.signal(signum, stop)
    try:
        sys.exit(main())
    except (OSError, RuntimeError, sp.SubprocessError) as error:
        print(f"ERROR: {error}; results: {ROOT}", file=sys.stderr)
        sys.exit(1)
