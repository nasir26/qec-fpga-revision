#!/usr/bin/env bash
# =============================================================================
#  build_shor.sh  —  compile & link the Shor (and optional Rep-3) QEC kernels
#                    for Xilinx Alveo U55C using Vitis 2023.2
# =============================================================================
#  Usage:
#     ./build_shor.sh              # build shor_qec_kernel only
#     ./build_shor.sh rep3         # also build rep3_qec_kernel (warm-up)
#     ./build_shor.sh emu          # hw_emu target for C/RTL co-sim
# =============================================================================
set -euo pipefail

# -------- toolchain / platform ------------------------------------------------
: "${XILINX_VITIS:=/home/abhishek/tools/Vitis/2023.2}"
: "${XILINX_VIVADO:=/home/abhishek/tools/Vivado/2023.2}"
: "${XILINX_XRT:=/opt/xilinx/xrt}"
: "${PLATFORM:=/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm}"

# shellcheck disable=SC1091
source "${XILINX_VITIS}/settings64.sh"
# shellcheck disable=SC1091
source "${XILINX_XRT}/setup.sh"

TARGET="hw"
BUILD_REP3="no"
for arg in "$@"; do
    case "$arg" in
        rep3) BUILD_REP3="yes" ;;
        emu)  TARGET="hw_emu"  ;;
        sw)   TARGET="sw_emu"  ;;
        *)    echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

echo "── target   : $TARGET"
echo "── platform : $PLATFORM"

# Common v++ flags — match the style you use for v05.
VXX_COMMON=(
    -t "$TARGET"
    --platform "$PLATFORM"
    --save-temps
    --log_dir ./vxx_logs
    --report_dir ./vxx_reports
    --profile.data all:all:all
)

# -------- Shor kernel ---------------------------------------------------------
echo
echo "============================================================"
echo "  Compiling shor_qec_kernel.cpp → shor_qec_kernel.xo"
echo "============================================================"
v++ -c "${VXX_COMMON[@]}" \
    -k shor_qec_kernel \
    -o shor_qec_kernel.xo \
    shor_qec_kernel.cpp

echo
echo "============================================================"
echo "  Linking shor_qec_kernel.xclbin  (config: shor_link.cfg)"
echo "============================================================"
v++ -l "${VXX_COMMON[@]}" \
    --config shor_link.cfg \
    -o shor_qec_kernel.xclbin \
    shor_qec_kernel.xo

echo "✓ shor_qec_kernel.xclbin"

# -------- Rep-3 kernel (optional) --------------------------------------------
if [[ "$BUILD_REP3" == "yes" ]]; then
    echo
    echo "============================================================"
    echo "  Compiling rep3_qec_kernel.cpp → rep3_qec_kernel.xo"
    echo "============================================================"
    v++ -c "${VXX_COMMON[@]}" \
        -k rep3_qec_kernel \
        -o rep3_qec_kernel.xo \
        rep3_qec_kernel.cpp

    echo
    echo "============================================================"
    echo "  Linking rep3_qec_kernel.xclbin  (config: rep3_link.cfg)"
    echo "============================================================"
    v++ -l "${VXX_COMMON[@]}" \
        --config rep3_link.cfg \
        -o rep3_qec_kernel.xclbin \
        rep3_qec_kernel.xo

    echo "✓ rep3_qec_kernel.xclbin"
fi

echo
echo "=== build complete ==="
ls -lh ./*.xclbin
