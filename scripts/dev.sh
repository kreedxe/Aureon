#!/bin/sh
set -eu

if ! command -v pnpm >/dev/null 2>&1 || ! command -v uv >/dev/null 2>&1; then
  echo "Install Node.js, pnpm, Rust, and uv first. See README.md for platform prerequisites." >&2
  exit 1
fi

pnpm dev
