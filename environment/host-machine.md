# Host machine record

Fill this in before any measurement run. Timing claims are meaningless without it.

| Field | Value |
|---|---|
| Hostname | |
| CPU model, cores, base and boost clock | |
| RAM | |
| OS and kernel version | |
| Alveo card model and serial | U55C, |
| Device BDF(s) | observed in selftest.log: 0000:01:00.1, 0000:21:00.1, 0000:41:00.1, 0000:81:00.1 |
| PCIe generation and lane width (measured, `lspci -vv`) | |
| XRT version | selftest.log reports 2.16.204 |
| Shell / platform | xilinx_u55c_gen3x16_xdma_3_202210_1 |
| User groups (`id`) | |
| CPU governor during measurement | |
| Cores isolated / pinned for the host process | |
| Scheduling policy used | |

## Measurement hygiene checklist
- [ ] CPU governor set to `performance`
- [ ] Host process pinned to an isolated core
- [ ] Other load quiesced, recorded in the run log
- [ ] Card thermals recorded before and after (`xbutil examine`)
- [ ] Clock actually achieved on the card recorded from `xbutil examine`, not assumed to be 300 MHz
