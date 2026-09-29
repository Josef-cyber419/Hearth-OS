# Hearth OS: Bazzite (Fedora Atomic) + a TV-style home screen.
#
# Build:   podman build -t hearth-os .
# For AMD (and Intel) graphics; NVIDIA isn't supported.
#
# The "-deck" Bazzite images boot straight into Game Mode (gamescope); Hearth
# replaces Steam as the first thing you see, and Steam becomes one of its tiles.
ARG BASE_IMAGE=ghcr.io/ublue-os/bazzite-deck:stable

FROM scratch AS ctx
COPY image/build.sh /build.sh

FROM ${BASE_IMAGE}

COPY image/system_files /
COPY launcher/hearth /usr/lib/hearth/python/hearth
# For "What's new" on the home screen after an update.
COPY CHANGELOG.md /usr/share/hearth/CHANGELOG.md

# Stamped into /usr/share/hearth/version.json; CI passes VERSION (see CHANGELOG.md).
ARG HEARTH_VERSION=dev

RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=tmpfs,dst=/tmp \
    HEARTH_VERSION=${HEARTH_VERSION} /ctx/build.sh

RUN bootc container lint
