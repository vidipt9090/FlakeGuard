# M4 spike evidence (2026-11-21)

Throwaway workflows ran on branch `spike/m4` of `vidipt9090/flakeguard-demo` (not merged; PR #1 closed unmerged).
`poll_run.py` samples the jobs and artifacts APIs once a second and prints when each state change became visible.
`poll-live-run-44874270035.log` is its output for https://github.com/vidipt9090/flakeguard-demo/actions/runs/44874270035.
Results and the design choice are in `docs/DECISIONS.md` (M4-1 to M4-9).
