# Ubuntu 22.04 amd64, verified from Docker's official registry on 2026-10-24.
# Building on this older glibc baseline keeps the archive usable on LTS desktops.
FROM ubuntu:22.04@sha256:98510ac07bb4545e389be502a8918b385c018bfe4ceeb5ac7e0375c782268b04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 libpython3.10 python3-venv python3-tk python3-gi \
    gir1.2-atspi-2.0 at-spi2-core libatk-bridge2.0-0 libgtk-3-dev libx11-dev \
    gcc pkg-config xvfb xauth dbus-x11 xz-utils binutils \
    && rm -rf /var/lib/apt/lists/*
COPY desktop/requirements-build.txt /tmp/requirements-build.txt
RUN python3 -m venv --system-site-packages /opt/lockbox-build \
    && /opt/lockbox-build/bin/pip install --no-cache-dir -r /tmp/requirements-build.txt
ARG BUILDER_UID=1000
ARG BUILDER_GID=1000
RUN groupadd --gid "$BUILDER_GID" builder \
    && useradd --create-home --uid "$BUILDER_UID" --gid "$BUILDER_GID" builder
ENV PATH=/opt/lockbox-build/bin:$PATH
WORKDIR /work
USER builder
CMD ["sh", "desktop/linux/build.sh"]
