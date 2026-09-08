#!/usr/bin/env bash
# Build swhelper.
#
# The toolchain is resolved explicitly rather than taken off PATH: an Xcode.app
# selected by xcode-select can be half-updated so its swiftc refuses to load,
# while the CommandLineTools toolchain beside it works. Each candidate compiler
# is paired with its own SDK, because the CLT swiftc cannot find the standard
# library without one. Only the search is quiet; the build itself is not, or a
# compile error looks like a missing toolchain.
set -euo pipefail

cd "$(dirname "$0")"

usable() { [ -n "${1:-}" ] && [ -x "${1:-}" ] && "$1" --version >/dev/null 2>&1; }

SWIFTC="${SWIFTC:-}" SDK="${SDKROOT:-}"
if ! usable "$SWIFTC"; then
    SWIFTC="$(xcrun --find swiftc 2>/dev/null || true)"
    SDK="$(xcrun --show-sdk-path 2>/dev/null || true)"
fi
if ! usable "$SWIFTC"; then
    SWIFTC=/Library/Developer/CommandLineTools/usr/bin/swiftc
    SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
fi
if ! usable "$SWIFTC"; then
    echo "no working swiftc found; try: xcode-select --install" >&2
    exit 1
fi

echo "building with $SWIFTC (sdk: $SDK)"
"$SWIFTC" -sdk "$SDK" -O -o swhelper swhelper.swift
echo "built $(pwd)/swhelper"
