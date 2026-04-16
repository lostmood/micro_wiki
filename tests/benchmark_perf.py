#!/usr/bin/env python3
"""
Performance baseline benchmark for Wiki Engine v1.

Tests:
1. wiki_search performance at 100/1k page scale
2. Index rebuild performance at 100/1k page scale
"""

import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List
import statistics

from wiki_engine.mcp_tools import wiki_search, wiki_status
from wiki_engine.index_manager import IndexManager


def create_test_pages(wiki_root: Path, count: int) -> None:
    """Create test pages with realistic content."""
    wiki_dir = wiki_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    for i in range(count):
        page_id = f"test-page-{i:04d}"
        content = f"""---
title: Test Page {i}
created: 2026-04-14T00:00:00Z
updated: 2026-04-14T00:00:00Z
confidence: 0.9
---

# Test Page {i}

This is test page number {i} for performance benchmarking.

## Content

Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

Related pages: [[test-page-{(i-1) % count:04d}]] [[test-page-{(i+1) % count:04d}]]

## Tags

- performance
- benchmark
- test-{i % 10}
"""
        page_path = wiki_dir / f"{page_id}.md"
        page_path.write_text(content)


def benchmark_search(wiki_root: Path, query: str, iterations: int = 10) -> Dict[str, Any]:
    """Benchmark wiki_search performance."""
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        result = wiki_search(str(wiki_root), query, limit=10)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

        if result["status"] != "success":
            raise RuntimeError(f"Search failed: {result}")

    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0,
        "min": min(times),
        "max": max(times),
        "p95": sorted(times)[int(len(times) * 0.95)],
    }


def benchmark_index_rebuild(wiki_root: Path, iterations: int = 3) -> Dict[str, Any]:
    """Benchmark index rebuild performance."""
    times = []
    index_dir = wiki_root / ".index"

    for _ in range(iterations):
        # Clear index
        if index_dir.exists():
            shutil.rmtree(index_dir)

        # Rebuild
        start = time.perf_counter()
        idx = IndexManager(wiki_root)
        idx.compact()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0,
        "min": min(times),
        "max": max(times),
    }


def run_benchmark(scale: int) -> Dict[str, Any]:
    """Run full benchmark suite at given scale."""
    print(f"\n{'='*60}")
    print(f"Running benchmark at {scale} pages scale")
    print(f"{'='*60}")

    with tempfile.TemporaryDirectory() as tmpdir:
        wiki_root = Path(tmpdir)

        # Setup
        print(f"Creating {scale} test pages...")
        create_test_pages(wiki_root, scale)

        # Initial index build
        print("Building initial index...")
        idx = IndexManager(wiki_root)
        idx.compact()

        # Benchmark search
        print("Benchmarking wiki_search (10 iterations)...")
        search_results = benchmark_search(wiki_root, "test performance", iterations=10)

        print(f"  Mean:   {search_results['mean']*1000:.2f}ms")
        print(f"  Median: {search_results['median']*1000:.2f}ms")
        print(f"  P95:    {search_results['p95']*1000:.2f}ms")
        print(f"  StdDev: {search_results['stdev']*1000:.2f}ms")

        # Benchmark index rebuild
        print("Benchmarking index rebuild (3 iterations)...")
        rebuild_results = benchmark_index_rebuild(wiki_root, iterations=3)

        print(f"  Mean:   {rebuild_results['mean']*1000:.2f}ms")
        print(f"  Median: {rebuild_results['median']*1000:.2f}ms")
        print(f"  StdDev: {rebuild_results['stdev']*1000:.2f}ms")

        return {
            "scale": scale,
            "search": search_results,
            "index_rebuild": rebuild_results,
        }


def main():
    """Run all benchmarks and output results."""
    print("Wiki Engine v1 Performance Baseline")
    print("=" * 60)

    results = []

    # 100 pages
    results.append(run_benchmark(100))

    # 1000 pages
    results.append(run_benchmark(1000))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    for r in results:
        scale = r["scale"]
        search_p95 = r["search"]["p95"] * 1000
        rebuild_mean = r["index_rebuild"]["mean"] * 1000

        print(f"\n{scale} pages:")
        print(f"  wiki_search P95:     {search_p95:.2f}ms")
        print(f"  index_rebuild mean:  {rebuild_mean:.2f}ms")

    print("\n" + "="*60)
    print("Benchmark complete!")
    print("="*60)


if __name__ == "__main__":
    main()
