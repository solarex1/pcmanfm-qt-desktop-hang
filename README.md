# pcmanfm-qt desktop hang

A reproduction of a deadlock in pcmanfm-qt's desktop as it starts, for
[lxqt/pcmanfm-qt#2213](https://github.com/lxqt/pcmanfm-qt/pull/2213). The desktop takes its D-Bus
name, `org.pcmanfm.PCManFM`, but never answers a call or draws the desktop: its main thread waits
forever in GLib as the desktop replaces its first folder.

It runs fresh starts of Debian 13's pcmanfm-qt, alone and in an LXQt session, with and without added
CPU load, and the same loaded starts with #2213's change. The image takes Debian 13's packages as
they are when it's built, so a later update, such as GLib's fix, can change what it shows; each job
prints the versions it ran.

## Results

[Run 41075328737](https://github.com/solarex1/pcmanfm-qt-desktop-hang/actions/runs/41075328737), on
GitHub's `ubuntu-24.04` runners with 4 CPUs, with Debian 13's pcmanfm-qt 2.1.0-2 (2.1.0-2+fix1 with
the change), libfm-qt6-15 2.1.0-1+b1 and libglib2.0-0t64 2.84.4-3~deb13u5:

| 40 fresh starts | Stock, no added load | Stock, CPU loaded | With #2213's change, CPU loaded |
| --- | --- | --- | --- |
| `pcmanfm-qt --desktop` | 0 hung | 18 hung | 0 hung |
| `startlxqt` | 0 hung | 12 hung | 0 hung |

No start had any other outcome. Under load, the starts that didn't hang took about as long with
and without the change: medians of 0.7 s alone, and 2.2 s and 2.0 s in the session.

Every hung start's main thread waits in the same place. Start 10 of the loaded `desktop` job, from
its artifact: its frames from #3 on, with addresses and arguments cut, omitting intermediate frames
that release references:

```text
#3  g_context_specific_group_request_state () at ../../../gio/gcontextspecificgroup.c:157
#4  g_context_specific_group_remove () at ../../../gio/gcontextspecificgroup.c:224
#5  g_unix_mount_monitor_finalize () at ../../../gio/gunixmounts.c:2605
#7  g_unix_volume_monitor_finalize () at ../../../gio/gunixvolumemonitor.c:77
#9  g_union_volume_monitor_finalize () at ../../../gio/gunionvolumemonitor.c:72
#12 Fm::VolumeManager::~VolumeManager () at ./src/core/volumemanager.cpp:32
#19 Fm::Folder::~Folder () at ./src/core/folder.cpp:109
#27 PCManFM::DesktopWindow::setDesktopFolder () at ./pcmanfm/desktopwindow.cpp:513
#28 PCManFM::DesktopWindow::updateFromSettings () at ./pcmanfm/desktopwindow.cpp:958
#29 PCManFM::Application::createDesktopWindow () at ./pcmanfm/application.cpp:824
#30 PCManFM::Application::desktopManager () at ./pcmanfm/application.cpp:471
#31 PCManFM::Application::parseCommandLineArgs () at ./pcmanfm/application.cpp:248
#32 PCManFM::Application::exec () at ./pcmanfm/application.cpp:349
#33 main () at ./pcmanfm/pcmanfm.cpp:12
```

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
