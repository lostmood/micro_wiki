# Day2 交付总结

## 交付状态：✅ 全部完成

### 核心交付：propose -> lint -> apply 三阶段工作流

**交付物：**
- `wiki_engine/workflow.py` - 完整的三阶段工作流引擎
- `tests/test_workflow.py` - 7 个完整测试用例

### 关键特性实现

#### 1. propose_patch (Stage 1) ✅
- 生成唯一 patch_id
- 写入 .pending/ 目录
- 自动运行 lint 检查
- 记录 base_commit 用于 TOCTOU 防护

#### 2. apply_patch (Stage 2) ✅
- **签名验证**：完整的 HMAC 签名验证（含 nonce 防重放）
- **patch_id 匹配**：显式校验 `signed_approval.patch_id == patch_id`（@codex Day2 提醒）
- **TOCTOU 防护**：
  - 第一次检查：apply 前验证 base_commit
  - 第二次检查：获取锁后再次验证（双重保护）
- **ACL 验证**：审批人身份 + 权限检查
- **原子应用**：lease 保护 + 审计日志 + git commit

#### 3. WikiLinter 集成 ✅
- propose 阶段自动运行 lint
- 5 条阻断规则全部集成
- lint 失败时 apply 被拒绝

### 测试覆盖

**新增测试：7 个**
1. `test_propose_patch_generates_patch_id` - 验证 patch_id 生成和保存
2. `test_apply_patch_verifies_signature` - 验证签名验证
3. `test_apply_patch_rejects_patch_id_mismatch` - 验证 patch_id 匹配检查
4. `test_apply_patch_toctou_protection` - 验证 TOCTOU 防护
5. `test_apply_patch_rejects_unauthorized_approver` - 验证 ACL
6. `test_apply_patch_success_flow` - 验证完整成功流程
7. `test_apply_patch_double_check_toctou_under_lock` - 验证锁下双重检查

**全套测试结果：23/23 通过**
- Lock Manager: 4/4 ✓
- ACL: 5/5 ✓
- Concurrent: 2/2 ✓
- Lint: 5/5 ✓
- Workflow: 7/7 ✓

### 关键设计决策

**ADR-004: 为什么需要双重 TOCTOU 检查？**
- **决策**：在获取锁前检查一次，获取锁后再检查一次
- **理由**：
  - 第一次检查：快速失败，避免不必要的锁竞争
  - 第二次检查：防止锁获取期间的并发修改
- **场景**：两个 agent 同时 apply 不同 patch，都通过第一次检查，但只有一个能获取锁并成功 apply

**ADR-005: 为什么显式检查 patch_id 匹配？**
- **决策**：`signed_approval.patch_id` 必须等于 `patch_id` 参数
- **理由**：防止签名跨 patch 复用攻击
- **场景**：攻击者用合法的 patch-A 签名去 apply patch-B

**ADR-006: 为什么 lint 在 propose 阶段运行？**
- **决策**：propose 时立即运行 lint，结果存储在 patch 中
- **理由**：
  - 快速反馈：agent 立即知道问题
  - apply 时只需检查 lint_status，无需重新运行
  - 审计友好：lint 结果永久记录

### 接口规范

**propose_patch 接口：**
```python
def propose_patch(
    agent_id: str,
    operation: str,
    pages: List[str],
    diff: str,
    confidence: float,
    sources: List[str]
) -> dict
```

**返回：**
```python
{
    "status": "success",
    "patch_id": "patch-20260414-123456",
    "requires_approval": true,
    "confidence": 0.95,
    "lint_status": "passed",
    "lint_errors": null
}
```

**apply_patch 接口：**
```python
def apply_patch(
    patch_id: str,
    signed_approval: dict,
    expected_base_commit: str
) -> dict
```

**返回（成功）：**
```python
{
    "status": "success",
    "change_id": "ch-20260414-123456",
    "commit_hash": "abc123...",
    "applied_at": 1234567890.123
}
```

**返回（失败）：**
```python
{
    "status": "failed",
    "reason": "base_commit_changed",
    "message": "Base commit changed during lock acquisition",
    "expected": "abc123...",
    "actual": "def456..."
}
```

### 安全保证

1. ✅ **防重放攻击**：nonce + TTL + 原子化消费
2. ✅ **防签名复用**：显式 patch_id 匹配检查
3. ✅ **防 TOCTOU**：双重 base_commit 验证
4. ✅ **防并发冲突**：lease 保护 + fencing token
5. ✅ **防权限绕过**：ACL 身份 + 权限双重验证

### 审计追踪

所有操作记录到 `.audit/` 目录：
- patch 创建时间
- lint 结果
- 审批人身份
- 签名信息
- change_id（全局唯一）
- git commit hash

### 下一步（Day3-4）

按照原计划，接下来需要：
- Day 5: index.ops + shadow_evaluator
- Day 6-7: MCP 接口实现

但 Day2 的核心工作流已经完成，可以进入下一阶段。

---

**签名**: [宪宪/Opus-4.6🐾]
**时间**: 2026-04-14
**状态**: Day2 完成，测试 23/23 通过，可进入 Day3
