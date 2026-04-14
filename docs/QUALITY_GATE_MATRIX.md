# Quality Gate Matrix (Day2 Baseline)

## Scope

This matrix defines the minimum gate for `propose -> lint -> apply` integration.

## Lint Rules (Blocking)

| Rule | Code | Severity | Description |
|------|------|----------|-------------|
| Frontmatter required | `missing_frontmatter` | error | Markdown page must start with YAML frontmatter block. |
| Frontmatter YAML valid | `invalid_frontmatter` | error | Frontmatter must parse into a mapping object. |
| Required fields present | `missing_required_field` | error | Required metadata keys must exist. |
| Confidence in range | `invalid_confidence` | error | `confidence` must be numeric in `[0, 1]`. |
| Source refs present | `missing_source_refs` | error | `source_refs` must be a non-empty list of non-empty strings. |
| Unique page IDs | `duplicate_page_id` | error | `page_id` values must be unique across wiki pages. |
| Wiki links resolvable | `broken_wikilink` | error | `[[page_id]]` links must point to existing pages. |

## Apply Gate Conditions

1. `lint_result.passed == true`
2. `signed_approval.patch_id == patch_id`
3. `signed_approval.expected_base_commit == expected_base_commit`
4. ACL signature verification must return `valid`
5. Permission check for operation must pass

## Failure Contract

When lint fails, API returns:

```json
{
  "status": "failed",
  "reason": "lint_failed",
  "errors": [
    {
      "code": "broken_wikilink",
      "file": "wiki/concepts/a.md",
      "message": "Wikilink target 'x' does not exist."
    }
  ]
}
```

## Test Baseline

Current baseline tests:

- `tests/test_lock_manager.py` (4 tests)
- `tests/test_acl.py` (5 tests)
- `tests/test_lock_concurrent.py` (2 tests)
- `tests/test_lint.py` (5 tests)

Total baseline: **16 tests**
