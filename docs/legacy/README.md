# Legacy: the submitted artifact

Read-only. Never edit anything in this directory. It exists so that every claim in the
revised manuscript can be diffed against what was actually submitted.

- `manuscript/` the submitted LaTeX, figures, class file, bibliography, and compiled PDF.
- `implementation/` the implementation archive as received.

`shor_qec_kernel.xclbin` and `shor_qec_kernel.xo` are present in `implementation/`
(`implementation/BINARIES_OMITTED.txt` describes an earlier portable copy that dropped them;
that note is now stale). Every file in this directory was verified byte-for-byte against the
two source archives before ingest: `ARCHIVE_CHECKSUMS.sha256` hashes the two zips as received,
`FILE_MANIFEST.sha256` hashes every extracted file. Nothing here was edited, reformatted, or
regenerated.

There is no `steane_qec_kernel.xclbin`, `.xo`, `compile_summary`, or `link_summary` anywhere in
`implementation/`, and `build.log` / `xcd.log` mention only the Shor kernel build. As far as this
archive shows, the Steane and Rep-3 kernels were never taken through `v++` at all; Tables 2 and 3
Steane rows have no traceable synthesis or place-and-route report.

## The file to read first

`implementation/selftest.log`. Its closing lines state that the self-test ran against the
software decoder and that the xclbin was not exercised. The manuscript presents those results
as hardware verification. Everything in the revision campaign follows from that discrepancy.
