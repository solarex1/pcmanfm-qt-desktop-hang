# Native startup reproduction

Run [minimal.py](minimal.py) against an installed, unmodified pcmanfm-qt binary on Linux:

```sh
python3 minimal.py
# Or: python3 minimal.py /path/to/pcmanfm-qt
```

It needs Python 3, Xvfb with `xvfb-run` and `xauth`, `dbus-run-session`, `dbus-send`, `xwininfo`
and `gdb`. On Debian, the extra tools are in `xvfb xauth dbus-bin dbus-daemon x11-utils gdb`;
on Arch, `xorg-server-xvfb xorg-xauth dbus xorg-xwininfo gdb python`. Nothing needs Docker,
GitHub Actions, a full LXQt session, root, or changing your installed application.

The script creates its own X display, session bus and working directory. It starts two busy
workers and the application on one available logical CPU, then launches `pcmanfm-qt --desktop`
up to 40 times, with a fresh home each time. A responsive start answers a D-Bus call and has a
desktop window. It kills that instance before the next start.
The private X server stays running between attempts; it is started with `-noreset`.

At the first startup that is not ready after 15 seconds, it checks that its child still owns the
bus name and attempts a backtrace. The program's output and debugger result remain in the
printed `pcmanfm-repro-*` directory in your current directory. A failed dependency or setup is
an error, not a reproduced deadlock. A backtrace is needed to identify the specific GLib wait.
For useful library symbols, install your distribution's debug symbols or supply its
`DEBUGINFOD_URLS`; gdb's single attempt is limited to 90 seconds.
To keep that attempt small, it explicitly loads shared-library symbols for GIO and libfm-qt.
Partial debugger output remains in `backtrace.txt` if that limit or the probe's deadline interrupts it.

Exit codes: 0 means all 40 starts answered; 2 means a startup was not ready and gdb captured a
trace; 3 means startup was not ready but gdb failed to capture a trace; 1 means setup, execution,
cancellation or deadline failure. None of these alone proves the particular GLib cause.

The probe has a 180-second deadline; its launcher waits at most 200 seconds. Ctrl-C stops owned
processes. If the launcher is killed, the independent probe deadline remains; if the probe is
killed, Linux parent-death signals end its direct children and the X/bus wrappers finish.
Generated files remain for inspection. The private display also uses X's normal socket/lock paths
under `/tmp`; abrupt X termination may leave those display-specific paths. Your existing home,
display, bus and desktop settings are not used.

This smaller workload still needs its own master/control validation; the earlier README's run
counts apply to `repro.py`, not this script.
