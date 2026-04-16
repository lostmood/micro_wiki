# Wiki Engine v1 Performance Baseline

**Date**: 2026-04-15
**Version**: v1.0
**Test Environment**: Linux 6.6.123+, Python 3.12.3

## Overview

This document establishes performance baselines for Wiki Engine v1 core operations at two scale points: 100 pages and 1,000 pages.

## Test Methodology

### Test Setup

- **Tool**: `tests/benchmark_perf.py`
- **Scales**: 100 pages, 1,000 pages
- **Page Content**: Realistic markdown with frontmatter, ~200 chars body, 2 wikilinks
- **Iterations**:
  - wiki_search: 10 iterations per scale
  - index rebuild: 3 iterations per scale
- **Metrics**: Mean, Median, P95, StdDev

### Test Operations

1. **wiki_search**: Full-text search with query "test performance", limit=10
2. **Index rebuild**: Complete index compaction from scratch (`.index/` cleared)

## Baseline Results

### 100 Pages Scale

| Operation | Mean | Median | P95 | StdDev |
|-----------|------|--------|-----|--------|
| wiki_search | 63.12ms | 60.76ms | **86.63ms** | 8.81ms |
| index_rebuild | 0.74ms | 0.72ms | - | 0.15ms |

### 1,000 Pages Scale

| Operation | Mean | Median | P95 | StdDev |
|-----------|------|--------|-----|--------|
| wiki_search | 614.72ms | 575.40ms | **787.26ms** | 88.67ms |
| index_rebuild | 0.79ms | 0.78ms | - | 0.11ms |

## Key Observations

### Search Performance

- **Linear scaling**: ~10x pages → ~10x latency (86ms → 787ms P95)
- **Acceptable for v1**: Sub-second search at 1k pages
- **Variance**: ~14% StdDev at both scales (consistent)

### Index Rebuild Performance

- **Constant time**: ~0.75ms regardless of scale
- **Explanation**: Index rebuild only replays `.index/index.ops.jsonl`, not full wiki scan
- **Implication**: Compaction overhead is negligible

## Performance Targets (v1)

Based on these baselines, we establish the following targets:

| Scale | Operation | Target (P95) | Status |
|-------|-----------|--------------|--------|
| 100 pages | wiki_search | < 100ms | ✅ Pass (86.63ms) |
| 1k pages | wiki_search | < 1s | ✅ Pass (787.26ms) |
| Any scale | index_rebuild | < 10ms | ✅ Pass (0.79ms) |

## Regression Detection

Future changes should maintain:
- **wiki_search P95 < 100ms** at 100 pages
- **wiki_search P95 < 1s** at 1k pages
- **index_rebuild mean < 10ms** at any scale

Exceeding these thresholds indicates performance regression.

## Known Limitations

### Current Implementation

1. **Naive search**: Simple grep-based full-text search, no indexing
2. **No caching**: Every search scans all files
3. **No pagination**: Returns top-N results only

### Future Optimizations (v2+)

- Inverted index for sub-10ms search at 10k+ pages
- Result caching with TTL
- Incremental index updates (avoid full compaction)

## Reproduction

Run the benchmark:

```bash
PYTHONPATH=/home/haoshangbin/project/micro_wiki python tests/benchmark_perf.py
```

Expected output:
```
100 pages:
  wiki_search P95:     ~87ms
  index_rebuild mean:  ~0.7ms

1000 pages:
  wiki_search P95:     ~787ms
  index_rebuild mean:  ~0.8ms
```

## Conclusion

Wiki Engine v1 meets performance targets for small-to-medium wikis (< 1k pages):
- ✅ Sub-100ms search at 100 pages
- ✅ Sub-1s search at 1k pages
- ✅ Negligible index rebuild overhead

For larger wikis (10k+ pages), v2 should implement inverted indexing.

---

**Signed**: 布偶猫/宪宪 (Opus-4.6)
**Benchmark Tool**: `tests/benchmark_perf.py`
**Test Date**: 2026-04-15
