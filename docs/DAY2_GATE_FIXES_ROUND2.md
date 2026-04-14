# Day2 Gate Fixes - Round 2

**Date**: 2026-04-14
**Reviewer**: @codex
**Result**: Fixed 3 P0 + 1 P1 blocking issues

## Issues Fixed

### P0-1: Runtime Crash - Method Name Mismatch
**Location**: `workflow.py:376`
**Problem**: Called `self.linter.lint_pages()` but WikiLinter only has `lint_paths()` and `lint_wiki()`
**Fix**: Changed to `self.linter.lint_paths(pages_to_lint)`
**Impact**: Prevents runtime AttributeError when linting existing pages

### P0-2: Schema Violation - Wrong Frontmatter Fields
**Location**: `workflow.py:438-443`
**Problem**: Generated frontmatter with `id`, `created_at` but lint schema requires `page_id`, `title`, `updated`
**Fix**: Updated frontmatter generation:
```yaml
# Before (wrong):
id: {page_id}
created_at: {time.time()}

# After (correct):
page_id: {page_id}
title: {page_id}
updated: {time.time()}
```
**Impact**: Pages now pass lint validation after creation

### P0-3: Silent Failure - Git Commit Exception Handler
**Location**: `workflow.py:511-513`
**Problem**: Exception handler returned fake hash instead of failing
**Fix**: Changed to `raise RuntimeError(f"Git commit failed: {e.stderr}") from e`
**Impact**: Git failures now visible, no silent corruption

### P1: KeyError Risk - Missing Field Check
**Location**: `workflow.py:181-186`
**Problem**: Direct access `signed_approval["patch_id"]` could throw KeyError
**Fix**: Added field existence check before access:
```python
if "patch_id" not in signed_approval:
    return {"status": "failed", "reason": "missing_patch_id", ...}
```
**Impact**: Clear error message instead of exception

## Test Results
All 23 tests passing:
- 5 ACL tests
- 5 Lint tests
- 6 Lock Manager tests
- 7 Workflow tests

## Commit
```
bfde294 fix: Day2 gate P0 修复（方法名/schema/异常处理）
```

## Status
Ready for @codex final gate review.
