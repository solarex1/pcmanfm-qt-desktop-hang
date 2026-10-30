# Debian 13's pcmanfm-qt, or with FIX=1 the same package rebuilt from Debian's source with
# fix/0001-take-the-volume-monitor-before-the-desktop.patch, and what repro.py needs.
FROM debian:trixie
ARG FIX=0
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      pcmanfm-qt lxqt-session openbox xvfb dbus dbus-x11 x11-utils gdb python3 procps \
      gvfs gvfs-daemons ca-certificates \
 && useradd -m -u 1000 tester
COPY fix /fix
RUN if [ "$FIX" = 1 ]; then \
      sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources \
   && apt-get update \
   && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        dpkg-dev build-essential fakeroot devscripts \
   && DEBIAN_FRONTEND=noninteractive apt-get build-dep -y pcmanfm-qt \
   && mkdir /build && cd /build && apt-get source pcmanfm-qt \
   && cd pcmanfm-qt-*/ && patch -p1 < /fix/0001-take-the-volume-monitor-before-the-desktop.patch \
   && DEBEMAIL=repro@example.invalid DEBFULLNAME=repro dch --local +fix "The fix under test." \
   && dpkg-buildpackage -b -uc -us -j"$(nproc)" \
   && apt-get install -y --no-install-recommends /build/pcmanfm-qt_*+fix1_*.deb; \
    fi
COPY repro.py /repro.py
ENV DEBUGINFOD_URLS=https://debuginfod.debian.net
ENTRYPOINT ["python3", "/repro.py"]
CMD ["desktop", "40", "/out", "--load", "--user", "tester"]
