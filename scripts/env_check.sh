#!/usr/bin/env bash
# Verify the environment before any measurement. Fail loudly.
set -uo pipefail
fail=0
chk(){ if eval "$2" >/dev/null 2>&1; then echo "  ok    $1"; else echo "  FAIL  $1"; fail=1; fi }
echo "environment check"
chk "vitis (v++) on PATH"        "command -v v++"
chk "vivado on PATH"             "command -v vivado"
chk "xbutil on PATH"             "command -v xbutil"
chk "XILINX_XRT set"             "[ -n \"\${XILINX_XRT:-}\" ]"
chk "u55c platform present"      "ls /opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1"
chk "device visible to xbutil"   "xbutil examine | grep -qi u55c"
chk "user in render group"       "id -nG | tr ' ' '\n' | grep -qx render"
chk "python deps"                "python -c 'import numpy,scipy,matplotlib,stim,pymatching'"
echo
if [ $fail -ne 0 ]; then
  echo "environment check FAILED. Record the failure in docs/BLOCKERS.md."
  echo "Do NOT proceed with measurement runs on a partial environment."
  exit 1
fi
echo "environment check passed"
