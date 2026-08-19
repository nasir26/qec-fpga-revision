# Vitis HLS batch script for the reconstructed steane_qec_kernel
# (rtl/steane713/src/steane_qec_kernel.cpp). See docs/BLOCKERS.md B-003:
# this is a reconstruction, not the original source.
# Usage: vitis_hls -f run_hls_steane_qec_kernel.tcl
open_project -reset steane_qec_kernel_hls_proj
set_top steane_qec_kernel
add_files [file normalize [file join [file dirname [info script]] .. src steane_qec_kernel.cpp]]
open_solution -reset "solution1" -flow_target vitis
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 3.33 -name default
csynth_design
exit
