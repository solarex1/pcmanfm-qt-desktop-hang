"""Linux integration checks for minimal.py's failures and cancellation, in a disposable container."""
import os
from pathlib import Path
import signal
import subprocess as sp
import sys
import time


def processes():
    answer = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                answer[int(entry.name)] = (fields[0], int(fields[1]))
            except (FileNotFoundError, ProcessLookupError):
                pass
    return answer


def descendants(parent, snapshot):
    found = {parent}
    while True:
        more = {pid for pid, (_, ppid) in snapshot.items() if ppid in found}
        if more <= found:
            return found
        found |= more


script = Path(sys.argv[1]).resolve()
base = Path("lifecycle")
base.mkdir()
baseline = set(processes())
sentinel = (base / "existing-home").resolve()
sentinel.mkdir()
(sentinel / "protected.txt").write_text("existing caller data\n")
env = {**os.environ, "HOME": str(sentinel), "XDG_CONFIG_HOME": str(sentinel),
       "DISPLAY": ":7777", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/no/such/repro-bus"}
for case in ["missing-binary", "early-exit", "hangup-launcher", "kill-launcher", "kill-probe"]:
    work = base / case
    work.mkdir()
    with (work / "console.txt").open("w+") as log:
        binary = "/no/such/pcmanfm" if case == "missing-binary" else "/bin/false" if case == "early-exit" else "pcmanfm-qt"
        process = sp.Popen([sys.executable, str(script), binary], cwd=work, env=env, stdout=log, stderr=sp.STDOUT)
        try:
            if case in {"missing-binary", "early-exit"}:
                assert process.wait(timeout=25) == 1, case
            else:
                end = time.monotonic() + 30
                while "start 1: responsive" not in (work / "console.txt").read_text():
                    assert process.poll() is None, (case, (work / "console.txt").read_text())
                    assert time.monotonic() < end, case
                    time.sleep(0.05)
                roots = list(work.glob("pcmanfm-repro-*"))
                assert len(roots) == 1
                probe = int((roots[0] / "probe.pid").read_text())
                owned = descendants(process.pid, processes())
                assert probe in owned, (case, probe, owned)
                if case == "kill-probe":
                    os.kill(probe, signal.SIGKILL)
                else:
                    process.send_signal(signal.SIGHUP if case == "hangup-launcher" else signal.SIGKILL)
                end = time.monotonic() + 200
                while True:
                    live = {pid for pid, (state, _) in processes().items()
                            if pid not in baseline and pid != process.pid and state != "Z"}
                    if not live:
                        break
                    assert time.monotonic() < end, (case, live)
                    time.sleep(0.1)
                process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    text = (work / "console.txt").read_text()
    if case == "missing-binary":
        assert "binary not found" in text
    if case == "early-exit":
        assert "application exited 1" in text
    if case in {"missing-binary", "early-exit"}:
        assert "NOT READY" not in text
    remnants = sorted(str(path) for path in Path("/tmp").glob(".X*-lock"))
    sockets = sorted(str(path) for path in Path("/tmp/.X11-unix").glob("X*"))
    print(f"{case}: checked; X lock/socket remnants: {remnants + sockets}", flush=True)
    assert (sentinel / "protected.txt").read_text() == "existing caller data\n"
print("Five real-process failure/termination checks passed.", flush=True)
