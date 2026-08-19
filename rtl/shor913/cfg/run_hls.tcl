# Vitis HLS batch script for shor_qec_kernel (rtl/shor913/src/shor_qec_kernel.cpp).
# Usage: vitis_hls -f run_hls.tcl   (run from anywhere; paths below are repo-absolute)
# Produces: <run dir>/shor_qec_kernel_hls_proj/solution1/syn/report/shor_qec_kernel_csynth.rpt
# Copy that report into evidence/synthesis/ after every run, per docs/DECISIONS.md's
# "regenerate, do not retouch" rule -- never hand-edit a report.
open_project -reset shor_qec_kernel_hls_proj
set_top shor_qec_kernel
add_files [file normalize [file join [file dirname [info script]] .. src shor_qec_kernel.cpp]]
open_solution -reset "solution1" -flow_target vitis
set_part {xcu55c-fsvh2892-2L-e}
create_clock -period 3.33 -name default
csynth_design
exit
