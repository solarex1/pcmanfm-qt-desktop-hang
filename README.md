# pcmanfm-qt desktop hang

A reproduction of a deadlock in pcmanfm-qt's desktop as it starts, for
[lxqt/pcmanfm-qt#2213](https://github.com/lxqt/pcmanfm-qt/pull/2213). The desktop takes its D-Bus
name, `org.pcmanfm.PCManFM`, but never answers a call or draws the desktop: its main thread waits
forever in GLib as the desktop replaces its first folder.

It runs fresh starts of libfm-qt and pcmanfm-qt built from their master branches, on Arch Linux
(`Dockerfile.master`), and of Debian 13's pcmanfm-qt 2.1.0 (`Dockerfile`): alone and in an LXQt
session, with and without added CPU load, and the same loaded starts with #2213's change. Each
image takes its distribution's packages as they are when it's built, so a later update, such as
GLib's fix, can change what it shows; each job prints the versions it ran.

## Results

[Run 41085290877](https://github.com/solarex1/pcmanfm-qt-desktop-hang/actions/runs/41085290877),
on GitHub's `ubuntu-24.04` runners with 4 CPUs:

| 40 fresh starts | Stock, no added load | Stock, CPU loaded | With #2213's change, CPU loaded |
| --- | --- | --- | --- |
| master, `pcmanfm-qt --desktop` | 0 hung | 16 hung | 0 hung |
| master, `startlxqt` | 0 hung | 9 hung | 0 hung |
| Debian 13, `pcmanfm-qt --desktop` | 0 hung | 20 hung | 0 hung |
| Debian 13, `startlxqt` | 0 hung | 11 hung | 0 hung |

- **master:** libfm-qt `8e15258d` and pcmanfm-qt `11cc9ab4`, with the change #2213's commit
  `6538dadc` cherry-picked onto it; Qt 6.12.0, GLib 2.90.1, and liblxqt 2.4.0 (from the build's
  log).
- **Debian 13:** pcmanfm-qt 2.1.0-2 (2.1.0-2+fix1 with the change), libfm-qt6-15 2.1.0-1+b1, GLib
  2.84.4-3~deb13u5, and Qt 6.8.2 and liblxqt2 2.1.0-3 (from the build's log).

No start had any other outcome. Under load, the starts that didn't hang took about as long
without and with the change, each start's whole time in the harness, its setup and teardown
included: medians of 0.8 s and 0.6 s alone, and 1.5 s and 1.5 s in the session, on master;
0.8 s and 0.8 s, and 2.0 s and 2.3 s, on Debian 13.

Every hung start's main thread waits in the same place. Start 2 of master's loaded `desktop`
job, from its artifact: its frames from #3 on, with addresses and arguments cut, omitting
intermediate frames that release references:

```text
#3  g_context_specific_group_request_state () at ../glib/gio/gcontextspecificgroup.c:157
#4  g_context_specific_group_remove () at ../glib/gio/gcontextspecificgroup.c:224
#5  g_unix_mount_monitor_finalize () at ../glib/gio/gunixmounts.c:2568
#7  g_unix_volume_monitor_finalize () at ../glib/gio/gunixvolumemonitor.c:77
#9  g_union_volume_monitor_finalize () at ../glib/gio/gunionvolumemonitor.c:72
#12 Fm::VolumeManager::~VolumeManager () at /src/libfm-qt/src/core/volumemanager.cpp:32
#19 Fm::Folder::~Folder () at /src/libfm-qt/src/core/folder.cpp:108
#26 PCManFM::DesktopWindow::setDesktopFolder () at /src/pcmanfm-qt/pcmanfm/desktopwindow.cpp:522
#27 PCManFM::DesktopWindow::updateFromSettings () at /src/pcmanfm-qt/pcmanfm/desktopwindow.cpp:969
#28 PCManFM::Application::createDesktopWindow () at /src/pcmanfm-qt/pcmanfm/application.cpp:838
#29 PCManFM::Application::desktopManager () at /src/pcmanfm-qt/pcmanfm/application.cpp:477
#30 PCManFM::Application::parseCommandLineArgs () at /src/pcmanfm-qt/pcmanfm/application.cpp:252
#31 PCManFM::Application::exec () at /src/pcmanfm-qt/pcmanfm/application.cpp:353
#32 main () at /src/pcmanfm-qt/pcmanfm/pcmanfm.cpp:12
```

## Run it

On GitHub's runners: fork this repository, enable its workflows, and run `reproduce` from the
Actions tab. Each job builds its image and runs 40 fresh starts; the job's summary gives the
count, and its artifact holds every hung start's trace.

With Docker on Linux, as the workflow does:

```sh
docker build -f Dockerfile.master -t repro .
mkdir out
docker run --rm --cap-add SYS_PTRACE -v "$PWD/out:/out" repro desktop 40 /out --load --user tester
```

Without `-f Dockerfile.master`, the image has Debian 13's packages. With `--build-arg FIX=1`,
either image has #2213's change. `session` in place of `desktop` runs `startlxqt`; without
`--load`, nothing adds CPU load.

## What it does

`repro.py` gives each start a new X server (Xvfb), session bus and home, as a fresh login does, and
runs `pcmanfm-qt --desktop` (`desktop`) or `startlxqt` (`session`) as the user `tester`. A start
is fine when, within about 30 s of taking its D-Bus name, pcmanfm-qt both answers a D-Bus call and
has drawn its desktop window. If it hasn't and a process still owns the name, the start hung: gdb
saves every thread's stack as `out/start-N-trace.txt`, with symbols from the distribution's
debuginfod; attaching gdb is why the container needs `CAP_SYS_PTRACE`. Any other outcome is counted
apart, by name: no X server; no session bus, with dbus-daemon's answer in its verdict line; the
name never taken, with the start's output in `out/start-N-output.txt`; no owner of the name at the
end, with the bus's answer in `out/start-N-owner.txt`; or gdb getting no stack, with what gdb said
in `out/start-N-gdb.txt`. `--load` keeps twice as many busy processes as CPUs running throughout.

`Dockerfile.master` builds libfm-qt and pcmanfm-qt at the master commits it names; with `FIX=1`,
it cherry-picks #2213's commit onto pcmanfm-qt. `fix/0001-take-the-volume-monitor-before-the-desktop.patch`
is #2213's change on Debian's 2.1.0-2 source; with `FIX=1`, `Dockerfile` rebuilds Debian's package
with it, as version `2.1.0-2+fix1`.

## Why it hangs

The lines are at the master commits `Dockerfile.master` builds.

1. On every start, the desktop window's constructor opens the desktop folder
   ([`desktopwindow.cpp:129-133`](https://github.com/lxqt/pcmanfm-qt/blob/11cc9ab4a3d8ed8d4b318606856939bead658f5f/pcmanfm/desktopwindow.cpp#L129-L133)), and `createDesktopWindow()`
   then calls `updateFromSettings()` ([`application.cpp:838`](https://github.com/lxqt/pcmanfm-qt/blob/11cc9ab4a3d8ed8d4b318606856939bead658f5f/pcmanfm/application.cpp#L838)), whose
   `setDesktopFolder()` drops that folder before it opens the desktop folder again
   ([`desktopwindow.cpp:510-529`](https://github.com/lxqt/pcmanfm-qt/blob/11cc9ab4a3d8ed8d4b318606856939bead658f5f/pcmanfm/desktopwindow.cpp#L510-L529)).
2. A folder holds libfm-qt's `VolumeManager` ([`folder.cpp:41`](https://github.com/lxqt/libfm-qt/blob/8e15258dd9513a21c19435c0dc4a6df8fad6ba4b/src/core/folder.cpp#L41)), a single
   instance kept only while something holds it
   ([`volumemanager.cpp:34-42`](https://github.com/lxqt/libfm-qt/blob/8e15258dd9513a21c19435c0dc4a6df8fad6ba4b/src/core/volumemanager.cpp#L34-L42)), and the `VolumeManager` holds
   GLib's volume monitor. pcmanfm-qt takes its own reference to the monitor only after
   `parseCommandLineArgs()` has made the desktop
   ([`application.cpp:353-361`](https://github.com/lxqt/pcmanfm-qt/blob/11cc9ab4a3d8ed8d4b318606856939bead658f5f/pcmanfm/application.cpp#L353-L361)). So dropping the first folder
   can drop the last reference, and when it does, the main thread finalizes the volume monitor.
3. The `VolumeManager` also gets the volume monitor on a low-priority job thread
   ([`volumemanager.cpp:21-25`](https://github.com/lxqt/libfm-qt/blob/8e15258dd9513a21c19435c0dc4a6df8fad6ba4b/src/core/volumemanager.cpp#L21-L25)). Finalizing GLib's unix mount
   monitor waits for its stop to finish; if another thread gets a mount monitor while the stop is
   pending, GLib aborts the stop without waking the waiting thread, a GLib bug with a fix in
   [GLib !5448](https://gitlab.gnome.org/GNOME/glib/-/merge_requests/5448). Added CPU load
   made the hang reproduce here: 56 of 160 loaded stock starts hung, and none of 160 without
   added load. That the load delays the low-priority job into the folder change is a plausible
   explanation; no trace records when the job got the monitor.
4. The job signals the main thread through a blocking queued connection, so in every trace
   libfm-qt's job threads wait for the main thread too, in `doActivate` (`QLatch::wait` with
   Qt 6.12, `QSemaphore::acquire` with 6.8).

#2213 has pcmanfm-qt take its own reference to the volume monitor before it makes the desktop, so
the folder change can't drop the last one.
