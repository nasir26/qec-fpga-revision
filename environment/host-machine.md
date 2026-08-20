# Host machine record

Fill this in before any measurement run. Timing claims are meaningless without it.

**Two different machines appear in this campaign's evidence** — do not conflate them:

## Machine A: original selftest.log capture host (not this session's working host)

| Field | Value |
|---|---|
| Device BDF(s) | observed in selftest.log: 0000:01:00.1, 0000:21:00.1, 0000:41:00.1, 0000:81:00.1 (four devices) |
| XRT version | selftest.log reports 2.16.204 (2023.2) |
| Shell / platform | xilinx_u55c_gen3x16_xdma_3_202210_1 |
| User | `abhishek`, not in `render` group at capture time |

## Machine B: this working host, `qec-fpga-revision` campaign machine (2026-08-19 onward)

| Field | Value |
|---|---|
| Hostname | `cdac` |
| CPU model, cores | AMD EPYC 7742, 64 cores |
| RAM | 251 GiB |
| OS and kernel version | Ubuntu 20.04.6 LTS, kernel 5.4.0-193-generic |
| Alveo card model and serial | U55C, serial not yet recorded |
| Device BDF(s) | `0000:8c:00.1` (single device) |
| PCIe generation and lane width | not yet measured (`lspci -vv`) |
| XRT version | 2.15.225 (2023.1) — **older than Machine A / the manuscript's assumed 2.16.204** |
| Shell / platform | `xilinx_u55c_gen3x16_xdma_base_3` — **different from the delivered xclbin's build platform** (`xilinx_u55c_gen3x16_xdma_3_202210_1`); compatibility not yet confirmed |
| User groups (`id`) | `cdac`: adm, cdrom, sudo, dip, plugdev, **render**, lxd, docker — already in `render`, unlike Machine A |
| `/sys/bus/pci/devices/0000:8c:00.1/resource4` permissions | `-rw-------` root:root — **not group-readable at all**; the `render`-group fix would not have solved Machine A's BAR4 problem here either (see docs/BLOCKERS.md B-001) |
| Vitis / Vitis HLS | 2023.2, confirmed working (`vitis_hls csynth_design` run for real, 2026-08-19) |
| Python | 3.8.10 (matches the `pyxrt.cpython-38` binary shipped with this XRT install) |
| `g++` | 9.x only (no `g++-10`+); this blocks source-building anything requiring `-std=c++20` (e.g. recent `stim` releases — pin to `stim==1.13.0`, which built cleanly, per `environment/requirements.txt`) |
| CPU governor during measurement | not yet recorded |
| Cores isolated / pinned for the host process | not yet done |
| Scheduling policy used | not yet done |

## Measurement hygiene checklist (Machine B, not yet done for any hardware run)
- [ ] CPU governor set to `performance`
- [ ] Host process pinned to an isolated core
- [ ] Other load quiesced, recorded in the run log
- [ ] Card thermals recorded before and after (`xbutil examine`)
- [ ] Clock actually achieved on the card recorded from `xbutil examine`, not assumed to be 300 MHz
