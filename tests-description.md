# Folder Similarity Scanner — Test Scenarios

This document captures the regression scenarios we exercise via automated tests. Each entry outlines the intent, fixture layout, and expected outcome.

## 1. Identical Nested `X` Folders
- **Layout**: Root `R` with children `X`, `A/X`, `B/nested/X`; each `X` holds the same file payload. `A` and `B` include extra unique files.
- **Expectation**: Scanner groups the three `X` folders as identical. Root `R` and parent folders must never appear in the same identical cluster. Raising the similarity threshold should demote `C/X` (with an extra file) out of the identical set.
- **Coverage**: `test_nested_x_directories_cluster_without_root`, `test_similarity_threshold_prevents_false_matches`.

## 2. Empty Directory Isolation
- **Layout**: Two empty folders (`empty_a`, `empty_b`) plus a third containing only subdirectories (no files).
- **Expectation**: No identical or near-duplicate group should form. Empty trees must not be treated as identical because they contain zero bytes.
- **Coverage**: `test_empty_directories_do_not_group`.

## 3. Distinct Files With Different Names
- **Layout**: Two folders (`alpha`, `beta`) each containing a single file of equal size but different names/content; another folder (`gamma`) shares file size but different payload.
- **Expectation**: With default `name_size` equality none of these should group; switching to `sha256` mode should still keep them apart because hashes differ.
- **Coverage**: `test_unique_files_remain_isolated`.

## 4. Parent Supersedes Children
- **Layout**: Folder `R` contains siblings `X` and `Y`; each of them contains identical subfolders (`A`, `B`) with matching payloads.
- **Expectation**: Only the parent folders (`X`, `Y`) appear in the identical group. Descendant folders (`A`, `B`) are suppressed when their parents already form a duplicate set, ensuring consolidation at higher levels.
- **Coverage**: `test_parent_supersedes_children`.

## 5. Case Sensitivity Toggle
- **Layout**: `case-root/A/file.txt` and `case-root/a/file.txt` on a case-sensitive FS.
- **Expectation**: Default behaviour keeps them separate; enabling `force_case_insensitive` groups them as identical.
- **Coverage**: *Planned*.

## 6. Permission & Drift Warnings
- **Layout**: Directories with an unreadable file and one mutated during scan.
- **Expectation**: Scanner raises `permission` and `unstable` warnings while still finishing.
- **Coverage**: *Planned*.

## 7. Deletion Workflow Guardrails
- **Layout**: RW sandbox with nested paths; plan includes legitimate and root-escaping entries.
- **Expectation**: Accepted paths move to quarantine; escape attempt rejected.
- **Coverage**: *Planned*.

The current automated suite covers scenarios 1–4. Remaining items are tracked for future expansion.***
