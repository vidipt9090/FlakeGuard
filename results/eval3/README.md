# Superseded: do not cite these files

The CSV files and `eval3_summary_table.md` in this folder were **not measured**. `scripts/generate_eval3_assets.py`
writes every number from values typed into the script, and the `command` column names commands that do not exist
(`python -m flakeguard.baselines.b1_rerun`, `python run_eval.py --condition ...`). The `git_sha` and `timestamp`
columns record when the script ran, not when anything was measured.

Measured results are produced by `scripts/run_eval.py` and written to `results/<label>/` (planted, injected, natural),
each file with its dataset, label type, N, exact command, date and commit. `GET /api/results` serves only those.

Do not run `generate_eval3_assets.py` again. The files are kept, not deleted, so that earlier documents that quote them
can be traced (see docs/DECISIONS.md, M8-2).
