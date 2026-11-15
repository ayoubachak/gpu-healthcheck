#!/usr/bin/env bash
# Clone and build wilicc/gpu-burn for Ada (RTX 4090, sm_89).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/external/gpu-burn"

for cmd in git make nvcc g++; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd (required to build gpu-burn)." >&2; exit 1; }
done

if [[ -e "$DIR" ]]; then
  echo "Directory already exists, not overwriting: $DIR" >&2
  exit 1
fi

git clone --depth 1 https://github.com/wilicc/gpu-burn.git "$DIR"

# gpu-burn's Makefile turns COMPUTE into a virtual architecture (PTX only).
# Build real sm_89 code instead, as its README describes for a single target.
NVCC_PATH="$(readlink -f "$(command -v nvcc)")"
CUDA_ROOT="$(dirname "$(dirname "$NVCC_PATH")")"
make -C "$DIR" CUDAPATH="$CUDA_ROOT" COMPUTE= \
  NVCCFLAGS="-gencode=arch=compute_89,code=sm_89"

echo "Ready: $DIR/gpu_burn"
