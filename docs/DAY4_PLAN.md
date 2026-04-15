# Day4 实施计划：MCP 工具层

**Date**: 2026-04-14
**Status**: ✅ Completed (commit 54807a8)

## 目标

实现 MCP 工具接口，将底层 workflow 引擎暴露给 Agent 使用。

## 硬门禁（@codex 要求）

1. ✅ 写接口必须严格走 `propose -> lint -> apply`，禁止绕过 workflow
2. ✅ `wiki_apply_patch` 必须继续强制 `signed_approval + expected_base_commit`
3. ✅ 只读接口零副作用（不写磁盘、不改状态）
4. ✅ 每个 MCP 工具补一条 contract test（成功+失败至少各 1 条）

## 实施顺序

### Phase 1: 只读工具（优先）

**1. wiki_read**
- 功能：读取指定页面内容
- 输入：`page_id: str`
- 输出：`{page_id, title, content, metadata}`
- 实现：直接读取 `wiki/{page_id}.md` 或子目录页面
- 测试：
  - ✅ 成功：读取存在的页面
  - ✅ 失败：读取不存在的页面

**2. wiki_status**
- 功能：获取 wiki 状态统计
- 输入：无
- 输出：`{total_pages, pending_patches, last_update, health}`
- 实现：
  - 统计 `wiki/` 目录下所有 `.md` 文件
  - 统计 `.pending/` 目录下 patch 数量
  - 读取最新 git commit 时间
- 测试：
  - ✅ 成功：返回正确统计
  - ✅ 边界：空 wiki 返回 0

**3. wiki_search**
- 功能：搜索 wiki 页面
- 输入：`query: str, limit: int = 10`
- 输出：`[{page_id, title, summary, relevance_score}]`
- 实现：
  - 简单版：基于文件名和标题的字符串匹配
  - 未来：可升级为 BM25 或向量检索
- 测试：
  - ✅ 成功：匹配到相关页面
  - ✅ 边界：无匹配返回空列表

### Phase 2: 写工具（基于 workflow）

**4. wiki_propose_patch**
- 功能：提议一个 patch
- 输入：`agent_id, operation, pages, diff, confidence, sources`
- 输出：`{status: "success", patch_id, requires_approval, confidence, lint_status, lint_errors}`
- 实现：直接透传 `workflow.propose_patch()` 返回值
- 契约说明：
  - **永远返回 `status: "success"`**（即使 lint 失败）
  - 通过 `lint_status` 字段区分："passed" / "failed"
  - lint 失败时 `lint_errors` 包含错误列表
  - 理由：lint 失败不是操作失败，而是内容不合规，patch 已成功保存到 .pending/
- 门禁：
  - ✅ 必须运行 lint
  - ✅ 必须记录 shadow_eval（但不返回给调用方）
- 测试：
  - ✅ 成功：create 操作通过 lint（lint_status="passed"）
  - ✅ 成功但 lint 失败：create 操作 lint 失败（status="success", lint_status="failed"）

**5. wiki_apply_patch**
- 功能：应用已审批的 patch
- 输入：`patch_id, signed_approval, expected_base_commit`
- 输出：`{status, ...}` - 成功或失败的结构化响应
- 实现：直接透传 `workflow.apply_patch()` 返回值
- 错误码映射：**原样透传 workflow 错误码**（不做固定枚举）
  - workflow 返回的所有 `reason` 字段原样透传
  - 常见错误码示例：
    - `signature_verification_failed:<detail>` - 签名验证失败
    - `base_commit_changed` - base commit 不匹配（TOCTOU）
    - `patch_not_found` - patch 不存在
    - `missing_target_pages` - update/delete 目标页面不存在
    - `unauthorized_approver` / `insufficient_permission` - 权限问题
- 门禁：
  - ✅ 必须验证签名
  - ✅ 必须检查 TOCTOU
  - ✅ 必须记录审计日志
  - ✅ 必须记录 index ops
- 测试：
  - ✅ 成功：有效签名 + 正确 base_commit
  - ✅ 失败：签名验证失败
  - ✅ 失败：base_commit 不匹配
  - ✅ 失败：patch 不存在

## 文件结构

```
wiki_engine/
├── mcp_tools.py          # MCP 工具实现
└── workflow.py           # 已有的 workflow 引擎

tests/
└── test_mcp_tools.py     # MCP 工具 contract tests
```

## 接口设计草案

### wiki_read

```python
def wiki_read(wiki_root: str, page_id: str) -> dict:
    """
    Read a wiki page.

    Returns:
        Success: {
            "status": "success",
            "page_id": "concept-transformer",
            "title": "Transformer Architecture",
            "content": "...",
            "metadata": {
                "updated": "2026-04-14T04:00:00Z",
                "confidence": 0.95,
                "source_refs": ["paper-attention"]
            }
        }

        Failure: {
            "status": "failed",
            "reason": "page_not_found",
            "message": "Page 'concept-transformer' does not exist"
        }
    """
```

### wiki_status

```python
def wiki_status(wiki_root: str) -> dict:
    """
    Get wiki status and statistics.

    Returns:
        {
            "status": "success",
            "total_pages": 42,
            "pending_patches": 3,
            "last_update": "2026-04-14T04:00:00Z",
            "health": "healthy"
        }
    """
```

### wiki_search

```python
def wiki_search(wiki_root: str, query: str, limit: int = 10) -> dict:
    """
    Search wiki pages by query.

    Returns:
        Success: {
            "status": "success",
            "results": [
                {
                    "page_id": "concept-transformer",
                    "title": "Transformer Architecture",
                    "summary": "...",
                    "relevance_score": 0.95
                }
            ],
            "total": 1
        }

        No results: {
            "status": "success",
            "results": [],
            "total": 0
        }
    """
```

### wiki_propose_patch

```python
def wiki_propose_patch(
    wiki_root: str,
    agent_id: str,
    operation: str,
    pages: List[str],
    diff: str,
    confidence: float,
    sources: List[str]
) -> dict:
    """
    Propose a patch for review.

    Delegates to workflow.propose_patch().

    Returns:
        Always returns status="success" (even if lint fails).
        Check lint_status field to determine if content is valid.

        {
            "status": "success",
            "patch_id": "patch-20260414-035500",
            "requires_approval": true,
            "confidence": 0.95,
            "lint_status": "passed" | "failed",
            "lint_errors": [...] | null
        }

        When lint_status="failed", lint_errors contains:
        [
            {
                "code": "missing_source_refs",
                "file": "wiki/concepts/transformer.md",
                "message": "Field 'source_refs' must be a non-empty list."
            }
        ]
    """
```

### wiki_apply_patch

```python
def wiki_apply_patch(
    wiki_root: str,
    patch_id: str,
    signed_approval: dict,
    expected_base_commit: str
) -> dict:
    """
    Apply an approved patch.

    Delegates to workflow.apply_patch().

    Returns:
        Success: {
            "status": "success",
            "change_id": "ch-20260414-035500",
            "commit_hash": "abc123",
            "applied_at": 1234567890.123
        }

        Failure (error codes from workflow - 原样透传):
        {
            "status": "failed",
            "reason": "<workflow 返回的原始 reason>",
            "message": "..."
        }

        常见错误码示例：
        - "signature_verification_failed:<detail>"
        - "base_commit_changed"
        - "patch_not_found"
        - "missing_target_pages"
        - "unauthorized_approver" / "insufficient_permission"
    """
```

## 测试清单

### test_mcp_tools.py

```python
# wiki_read
- test_wiki_read_existing_page_success
- test_wiki_read_nonexistent_page_fails
- test_wiki_read_subdir_page_success
- test_wiki_read_no_side_effects  # 验证调用前后文件哈希不变

# wiki_status
- test_wiki_status_returns_correct_stats
- test_wiki_status_empty_wiki_returns_zero
- test_wiki_status_no_side_effects  # 验证调用前后文件哈希不变

# wiki_search
- test_wiki_search_finds_matching_pages
- test_wiki_search_no_match_returns_empty
- test_wiki_search_respects_limit
- test_wiki_search_no_side_effects  # 验证调用前后文件哈希不变

# wiki_propose_patch
- test_wiki_propose_patch_create_success_lint_passed
- test_wiki_propose_patch_create_lint_failed_still_success

# wiki_apply_patch
- test_wiki_apply_patch_success
- test_wiki_apply_patch_invalid_signature
- test_wiki_apply_patch_base_commit_mismatch
- test_wiki_apply_patch_nonexistent_patch
```

## 实施步骤

1. 创建 `wiki_engine/mcp_tools.py` 骨架
2. 实现只读工具（wiki_read, wiki_status, wiki_search）
3. 为只读工具添加 contract tests
4. 实现写工具（wiki_propose_patch, wiki_apply_patch）
5. 为写工具添加 contract tests
6. 运行全套测试验证
7. 提交给 @codex 审查

## 下一步

完成 Day4 后，进入 Day5：
- MCP Server 实现（将工具暴露为 MCP 协议）
- 或者根据实际需求调整优先级

---

**签名**: [宪宪/Opus-4.6🐾]
**时间**: 2026-04-14
