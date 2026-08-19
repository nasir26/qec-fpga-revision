# Vitis HLS batch script for rep3_qec_kernel (rtl/rep3/src/rep3_qec_kernel.cpp).
# Usage: vitis_hls -f run_hls.tcl
open_project -reset rep3_qec_kernel_hls_proj
set_top rep3_qec_kernel
add_files [file normalize [file join [file dirname [info script]] .. src rep3_qec_kernel.cpp]]
open_solution -reset "solution1" -flow_target vitis
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 3.33 -name default
csynth_design
exit
