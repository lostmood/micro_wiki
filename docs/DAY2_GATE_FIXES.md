# Day2 Gate 反馈修复报告

## 修复状态：✅ 全部完成

### P0-1: Lint gate 实际调用 ✅

**问题描述：**
`_run_lint()` 固定返回 `passed=True`，没有真正调用 lint 规则。

**修复方案：**
- 实现真实的 lint 调用逻辑
- 对于现有页面：调用 `WikiLinter.lint_pages()`
- 对于新建页面：执行基础验证（confidence 范围、source_refs 非空）

**修复位置：**
- `wiki_engine/workflow.py:318-374` (_run_lint 方法)

**验证：**
- 测试通过，lint 现在会真实检查 confidence 和 source_refs

### P0-2: Apply 真实落地变更和提交 ✅

**问题描述：**
`apply_patch` 中的文件写入和 git commit 都是占位实现，导致审计记录与仓库真相不一致。

**修复方案：**
1. **_apply_changes()**: 实现真实的文件写入
   - create: 创建新文件（含 frontmatter）
   - update: 追加内容到现有文件
   - delete: 删除文件

2. **_git_commit()**: 实现真实的 git commit
   - `git add wiki/`
   - `git commit -m "详细消息"`
   - `git rev-parse HEAD` 获取真实 commit hash

**修复位置：**
- `wiki_engine/workflow.py:376-418` (_apply_changes 方法)
- `wiki_engine/workflow.py:467-512` (_git_commit 方法)

**验证：**
- 测试通过，apply 后文件真实创建
- Git commit 真实生成，commit hash 可追溯

### P1: patch_id 校验前移（防止 nonce 消耗） ✅

**问题描述：**
先 `verify_signature` 再校验 `patch_id`，错误的 patch_id 也会消费 nonce，可被恶意耗尽。

**修复方案：**
将 `patch_id` 一致性检查前移到签名验证之前：
1. 先检查 `signed_approval.patch_id == patch_id`
2. 只有 patch_id 正确才进行签名验证（消费 nonce）

**修复位置：**
- `wiki_engine/workflow.py:178-201` (apply_patch 方法)

**修复前顺序：**
```
1. Load patch
2. Verify lint
3. Verify signature (消费 nonce) ← 问题：错误 patch_id 也会消费
4. Check patch_id match
```

**修复后顺序：**
```
1. Load patch
2. Verify lint
3. Check patch_id match ← 前移：先检查 patch_id
4. Verify signature (消费 nonce) ← 只有 patch_id 正确才消费
```

**安全提升：**
- 防止攻击者用错误 patch_id 耗尽 nonce 池
- 保护签名验证资源

## 测试验证

**全套测试：23/23 通过**
```
Lock Manager:  4/4 ✓
ACL:          5/5 ✓
Concurrent:   2/2 ✓
Lint:         5/5 ✓
Workflow:     7/7 ✓
```

**关键测试验证：**
1. ✅ `test_apply_patch_success_flow` - 验证真实文件写入和 git commit
2. ✅ `test_apply_patch_rejects_patch_id_mismatch` - 验证 patch_id 前置检查
3. ✅ `test_propose_patch_generates_patch_id` - 验证 lint 真实调用

## 实现细节

### 真实 Lint 调用
```python
def _run_lint(self, patch: Patch) -> Any:
    # 查找受影响的页面文件
    pages_to_lint = []
    for page_id in patch.affected_pages:
        # 尝试常见位置
        if os.path.exists(f"{wiki_dir}/{page_id}.md"):
            pages_to_lint.append(...)

    # 对于新建页面，执行基础验证
    if not pages_to_lint and patch.operation == "create":
        # 检查 confidence 范围
        # 检查 source_refs 非空
        return LintResult(...)

    # 对现有页面调用真实 linter
    return self.linter.lint_pages(pages_to_lint)
```

### 真实文件应用
```python
def _apply_changes(self, patch: Patch):
    for page_id in patch.affected_pages:
        if patch.operation == "create":
            # 生成带 frontmatter 的完整页面
            content = f"""---
id: {page_id}
confidence: {patch.confidence}
source_refs: {patch.source_refs}
---
{patch.diff_content}
"""
            with open(page_path, 'w') as f:
                f.write(content)
```

### 真实 Git Commit
```python
def _git_commit(self, patch: Patch, approver_id: str, change_id: str) -> str:
    # Stage changes
    subprocess.run(["git", "add", "wiki/"], ...)

    # Create commit with detailed message
    commit_message = f"""Apply {patch.operation}: {pages}
Change ID: {change_id}
Patch ID: {patch.patch_id}
[{approver_id}🐾]"""

    subprocess.run(["git", "commit", "-m", commit_message], ...)

    # Get real commit hash
    result = subprocess.run(["git", "rev-parse", "HEAD"], ...)
    return result.stdout.strip()[:7]
```

## 影响分析

1. **P0-1 修复**：
   - 影响：所有 propose 操作
   - 行为变化：lint 现在会真实检查，不合规的 patch 会被拒绝
   - 向后兼容：是（只是从占位变为真实实现）

2. **P0-2 修复**：
   - 影响：所有 apply 操作
   - 行为变化：文件真实写入，git commit 真实生成
   - 向后兼容：是（占位实现本来就不应该在生产使用）

3. **P1 修复**：
   - 影响：签名验证流程
   - 行为变化：patch_id 不匹配时不再消费 nonce
   - 安全提升：防止 nonce 耗尽攻击

## 下一步

Day2 所有阻塞项已修复，等待 @codex 最终 gate 放行。

---

**签名**: [宪宪/Opus-4.6🐾]
**时间**: 2026-04-14
**状态**: P0-1/P0-2/P1 全部修复完成，测试 23/23 通过
