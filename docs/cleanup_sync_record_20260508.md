# 2026-05-08 cleanup and cloud sync record

## Scope

- Repository: `A股美股动量组合策略`
- Branch: `codex/subb-turnover-cost-cloud`
- Goal: clean disposable test/cache artifacts across repo directories and sync the surviving strategy changes to the remote branch.

## Candidate scan

Commands used before deletion:

- `git status -sb`
- `git ls-files | Select-String -Pattern '(^|/)(tests?/|test_.*\.py$|.*_test\.py$|.*test.*\.py$|__pycache__/|\.pyc$)'`
- `git status --ignored --short | Select-String -Pattern '(^|/)(tests?($|/)|test_|_test|__pycache__|\.pyc$|tmp|temp|scratch|测试|临时)'`
- PowerShell recursive scans excluding `.git`, `.vendor_libs`, `.worktrees`, `.codex_backups`, `docs`, `归档`, `历史文档`, `历史版本文件`, and `outputs`.

Result:

- No tracked, untracked, or ignored first-party test/cache deletion candidates were found.
- The only tracked `test` matches were inside `.vendor_libs/`, which is third-party dependency code and was preserved.

## Deleted

- None.

## Preserved

- `.vendor_libs/` third-party library test/helper files.
- `docs/`, formal research result directories, archives, backups, local market-data caches, and formal strategy scripts.
- Existing working-tree strategy changes in:
  - `mnt_bot V 7.0 plus.py`
  - `mnt_bot V 7.1 plus.py`
  - `mnt_bot V 7.2 plus.py`
  - `mnt_bot V 7.3 plus.py`
  - `mnt_bot V 7.5 plus.py`
  - `mnt_bot V 7.6 plus.py`

## Backup note

- Delete manifest: `.codex_backups/cleanup_delete_paths_20260508.txt`
- Because there were no delete targets, no file copy backup was required for this cleanup pass.

## Verification plan

- Run `python -m py_compile` on the six surviving V7.x strategy scripts.
- Remove any regenerated `__pycache__/` after verification.
- Run `git diff --check`.
- Commit and push only the intended strategy-script changes plus this cleanup record.
