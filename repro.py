#!/usr/bin/env python3
"""Fresh starts of pcmanfm-qt's desktop, counting the ones that hang.

Each start gets a new X server, a new session bus and a new home, as a fresh login does. In
`desktop` mode it runs `pcmanfm-qt --desktop` alone; in `session` mode, `startlxqt`, which starts
it with the rest of LXQt. A start hangs when pcmanfm-qt owns its D-Bus name, org.pcmanfm.PCManFM,
but answers no call and has drawn no desktop window by the deadline; then gdb prints every
thread's stack into OUT, and the start is ended.

    python3 repro.py MODE STARTS OUT [--load] [--user NAME]

--load keeps every CPU busy with twice as many spinning processes as CPUs while the starts run;
--user runs the session as that account (gdb still runs as root, which needs CAP_SYS_PTRACE).
"""
import os
import pwd
import signal
import subprocess
import sys
import tempfile
import time

NAME = "org.pcmanfm.PCManFM"
DEADLINE = 30


def run(args, env=None, timeout=10):
    """(exit status or None on a timeout, output)."""
    try:
        done = subprocess.run(args, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=timeout)
        return done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout} s"


def until(check, seconds, step=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(step)
    return check()


class Start:
    def __init__(self, number, out, account):
        self.number, self.out = number, out
        self.as_user = (["setpriv", f"--reuid={account.pw_uid}", f"--regid={account.pw_gid}",
                         "--init-groups"] if account else [])
        self.uid = account.pw_uid if account else os.getuid()
        self.home = tempfile.mkdtemp(prefix=f"home-{number}-")
        self.runtime = tempfile.mkdtemp(prefix=f"run-{number}-")
        os.makedirs(os.path.join(self.home, "Desktop"))
        for path in (self.home, os.path.join(self.home, "Desktop"), self.runtime):
            os.chown(path, self.uid, account.pw_gid if account else os.getgid())
        os.chmod(self.runtime, 0o700)
        self.display = 100 + number
        self.env = {"HOME": self.home, "XDG_RUNTIME_DIR": self.runtime,
                    "DISPLAY": f":{self.display}", "PATH": os.environ["PATH"], "LANG": "C.UTF-8",
                    "USER": account.pw_name if account else "root"}
        self.processes, self.bus_pid = [], None

    def spawn(self, args, as_user=True, log=None):
        process = subprocess.Popen((self.as_user if as_user else []) + args, env=self.env,
                                   stdin=subprocess.DEVNULL, stdout=log or subprocess.DEVNULL,
                                   stderr=subprocess.STDOUT if log else subprocess.DEVNULL,
                                   start_new_session=True)
        self.processes.append(process)
        return process

    def bus_call(self, *call, timeout=5):
        return run(self.as_user + ["dbus-send", "--session", "--print-reply",
                                   f"--reply-timeout={timeout * 1000}", *call], self.env, timeout + 5)

    def name_owned(self):
        status, out = self.bus_call("--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                                    "org.freedesktop.DBus.NameHasOwner", f"string:{NAME}")
        return status == 0 and "boolean true" in out

    def answers(self):
        return self.bus_call(f"--dest={NAME}", "/Application",
                             "org.freedesktop.DBus.Introspectable.Introspect")[0] == 0

    def desktop_window(self):
        status, out = run(["xwininfo", "-root", "-tree"], self.env)
        return status == 0 and "pcmanfm-desktop" in out

    def pcmanfm_pid(self):
        """The process that owns pcmanfm-qt's name on this start's bus."""
        status, out = self.bus_call("--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                                    "org.freedesktop.DBus.GetConnectionUnixProcessID", f"string:{NAME}")
        words = out.split()
        return int(words[-1]) if status == 0 and words and words[-1].isdigit() else None

    def judge(self, mode):
        """'fine', 'hung', or why the start couldn't be judged."""
        self.spawn(["Xvfb", f":{self.display}", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                   as_user=False)
        if not until(lambda: os.path.exists(f"/tmp/.X11-unix/X{self.display}"), 15):
            return "no X server"
        status, printed = run(self.as_user + ["dbus-daemon", "--session", "--fork",
                                              "--print-address=1", "--print-pid=1"], self.env)
        if status != 0:
            return f"no session bus ({printed.strip()})"
        address, pid = printed.split()[:2]
        self.env["DBUS_SESSION_BUS_ADDRESS"], self.bus_pid = address, int(pid)
        with open(os.path.join(self.out, f"start-{self.number}-output.txt"), "w") as log:
            self.spawn(["pcmanfm-qt", "--desktop"] if mode == "desktop" else ["startlxqt"], log=log)
        if not until(self.name_owned, DEADLINE):
            return "never took its D-Bus name"
        if until(lambda: self.answers() and self.desktop_window(), DEADLINE, step=0.5):
            return "fine"
        _, trace = run(["gdb", "-batch", "-iex", "set debuginfod enabled on", "-p",
                        str(self.pcmanfm_pid()), "-ex", "set pagination off",
                        "-ex", "thread apply all bt"], {**os.environ, **self.env}, 300)
        with open(os.path.join(self.out, f"start-{self.number}-trace.txt"), "w") as f:
            f.write(trace)
        return "hung"

    def end(self):
        for process in self.processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if self.bus_pid:
            try:
                os.kill(self.bus_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main(argv):
    mode, starts, out = argv[:3]
    load = "--load" in argv
    account = pwd.getpwnam(argv[argv.index("--user") + 1]) if "--user" in argv else None
    os.makedirs(out, exist_ok=True)
    os.makedirs("/tmp/.X11-unix", exist_ok=True)           # the X servers' sockets, for any user
    os.chmod("/tmp/.X11-unix", 0o1777)
    print(run(["dpkg-query", "-W", "pcmanfm-qt", "libfm-qt6-15", "libglib2.0-0t64"])[1], flush=True)
    print(f"{os.cpu_count()} CPUs", flush=True)
    spinners = [subprocess.Popen([sys.executable, "-c", "while True: pass"], stdin=subprocess.DEVNULL)
                for _ in range(2 * os.cpu_count())] if load else []
    results = []
    try:
        for number in range(1, int(starts) + 1):
            began = time.monotonic()
            start = Start(number, out, account)
            try:
                verdict = start.judge(mode)
            finally:
                start.end()
            results.append(verdict)
            print(f"start {number}: {verdict}, {time.monotonic() - began:.1f} s", flush=True)
    finally:
        for spinner in spinners:
            spinner.kill()
            spinner.wait()
    label = f"{mode}, {'loaded' if load else 'idle'}, as {account.pw_name if account else 'root'}"
    line = f"{label}: {results.count('hung')} of {len(results)} fresh starts hung"
    others = {v: results.count(v) for v in set(results) - {"fine", "hung"}}
    if others:
        line += f"; unjudged: {others}"
    print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
