# Hosts

## Which path may produce a publishable number

| Path | Location | Timing claims permitted |
|---|---|---|
| C++ XRT native API | `cpp/` | YES |
| C++ OpenCL (`host_decoder.cpp`) | `cpp/src/host_decoder.cpp` | YES |
| Python PyXRT | `python/` | NO, except as an explicitly labelled comparison point in the latency-budget figure |
| Software mirror | `python/`, `models/mirrors/` | NO, never. Mirrors exist to check correctness, not speed |

This split exists because conflating Python dispatch overhead with hardware decode latency is
the specific error that sank the prior submission. See ADR-003.

## Required change

`shor_qec_host.py` currently falls back to the software decoder when the BAR4 mmap and the XRT
buffer path both fail, and continues the run with a warning. Every host in this repository must
instead **abort** when the requested path is unavailable. A warning at the top of a log is not
sufficient protection; the prior submission's numbers passed through exactly that warning.
