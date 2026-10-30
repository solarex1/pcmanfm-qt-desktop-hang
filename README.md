# pcmanfm-qt desktop hang

A reproduction of a deadlock in pcmanfm-qt's desktop as it starts, for
[lxqt/pcmanfm-qt#2213](https://github.com/lxqt/pcmanfm-qt/pull/2213). The desktop takes its D-Bus
name, `org.pcmanfm.PCManFM`, but never answers a call or draws the desktop: its main thread waits
forever in GLib as the desktop replaces its first folder.

It runs fresh starts of Debian 13's pcmanfm-qt, alone and in an LXQt session, with and without added
CPU load, and the same loaded starts with #2213's change. The image takes Debian 13's packages as
they are when it's built, so a later update, such as GLib's fix, can change what it shows; each job
prints the versions it ran.

## Run it

On GitHub's runners: fork this repository, enable its workflows, and run `reproduce` from the
Actions tab. Each job builds the image and runs 40 fresh starts; the job's summary gives the count,
and its artifact holds every hung start's trace.

With Docker on Linux, as the workflow does:

```sh
docker build -t repro .
mkdir out
docker run --rm --cap-add SYS_PTRACE -v "$PWD/out:/out" repro desktop 40 /out --load --user tester
```

With `--build-arg FIX=1`, the image has #2213's change. `session` in place of `desktop` runs
`startlxqt`; without `--load`, nothing adds CPU load.

## What it does

`repro.py` gives each start a new X server (Xvfb), session bus and home, as a fresh login does, and
runs `pcmanfm-qt --desktop` (`desktop`) or `startlxqt` (`session`) as the user `tester`. A start
is fine when, within about 30 s of taking its D-Bus name, pcmanfm-qt both answers a D-Bus call and
has drawn its desktop window. If it hasn't and a process still owns the name, the start hung: gdb
saves every thread's stack as `out/start-N-trace.txt`, with symbols from Debian's debuginfod;
attaching gdb is why the container needs `CAP_SYS_PTRACE`. Any other outcome, such as no X server
or bus, the name never taken or no longer owned, or gdb getting no stack, is counted apart, by name,
with what was said saved in `out/`. `--load` keeps twice as many busy processes as CPUs running
throughout.

`fix/0001-take-the-volume-monitor-before-the-desktop.patch` is #2213's change on Debian's 2.1.0-2
source. With `FIX=1`, the image rebuilds Debian's package with it, as version `2.1.0-2+fix1`.

## Why it hangs

As it starts, the desktop replaces its first folder (`setDesktopFolder()`). Dropping that folder can
drop the last reference to libfm-qt's `VolumeManager`, and so to GLib's volume monitor, which the
main thread then finalizes. Finalizing GLib's unix mount monitor waits for its stop to finish; if
another thread gets a mount monitor while the stop is pending, GLib aborts the stop without waking
the waiting thread, a GLib bug with a fix in
[GLib !5448](https://gitlab.gnome.org/GNOME/glib/-/merge_requests/5448). libfm-qt gets the volume
monitor again on a job thread as the desktop starts (`GetGVolumeMonitorJob`), and in the traces
libfm-qt's job threads are blocked waiting for the main thread. #2213 has pcmanfm-qt take its own
reference to the volume monitor before it makes the desktop, so the folder change can't drop the
last one.

---

`repro.py`, the Dockerfile, the workflow, this README and the patch were written by an AI agent,
Claude Code, which also ran the experiments; Codex, another AI agent, reviewed them, read-only.
