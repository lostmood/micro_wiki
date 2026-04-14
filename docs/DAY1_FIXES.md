# Day1 审查反馈修复报告

## 修复状态：✅ 全部完成

### P1: 并发竞态修复 ✅

**问题描述：**
`renew_lease` 和 `release_lease` 没有使用全局锁保护，可能与 `takeover` 操作交错导致状态反转。

**修复方案：**
- `renew_lease`: 添加全局 flock 保护，与 takeover 使用同一把锁
- `release_lease`: 添加全局 flock 保护，与 takeover 使用同一把锁

**修复位置：**
- `wiki_engine/lock_manager.py:134-157` (renew_lease)
- `wiki_engine/lock_manager.py:159-176` (release_lease)

**回归测试：**
新增 `tests/test_lock_concurrent.py`，包含：
- `test_concurrent_renew_vs_takeover`: 验证 renew 与 takeover 不会竞态
- `test_concurrent_release_vs_takeover`: 验证 release 与 takeover 不会竞态

**测试结果：**
```
✓ test_concurrent_renew_vs_takeover passed
✓ test_concurrent_release_vs_takeover passed
```

### P2: 策略与接口文档一致性修复 ✅

**问题描述：**
`approval_policy.yaml` 规定 `shadow_eval` 默认隐藏，但 `MCP_INTERFACE.md` 的返回示例中暴露了 `shadow_eval`。

**修复方案：**
修改 `docs/MCP_INTERFACE.md:174-186`，移除返回示例中的 `shadow_eval` 字段，添加注释说明该字段默认隐藏。

**修复位置：**
- `docs/MCP_INTERFACE.md:174-186`

### P3: API key 常量时间比较修复 ✅

**问题描述：**
API key 比较使用普通字符串比较 `==`，存在时序攻击风险。

**修复方案：**
改用 `hmac.compare_digest()` 进行常量时间比较。

**修复位置：**
- `wiki_engine/acl.py:171-172`

**修复前：**
```python
return token_hash == approver["api_key_hash"]
```

**修复后：**
```python
return hmac.compare_digest(token_hash, approver["api_key_hash"])
```

## 完整测试验证

```bash
PYTHONPATH=. python tests/test_lock_manager.py      # 4/4 passed
PYTHONPATH=. python tests/test_acl.py               # 5/5 passed
PYTHONPATH=. python tests/test_lock_concurrent.py   # 2/2 passed
```

**总计：11/11 测试通过**

## 修复影响分析

1. **P1 修复**：
   - 影响范围：所有 lease 操作（acquire/renew/release/takeover）
   - 性能影响：renew 和 release 增加全局锁开销，但操作本身很快（<1ms）
   - 安全性提升：消除了并发竞态窗口

2. **P2 修复**：
   - 影响范围：接口文档
   - 无代码变更，仅文档澄清

3. **P3 修复**：
   - 影响范围：API key 验证路径
   - 性能影响：可忽略（hmac.compare_digest 与 == 性能相当）
   - 安全性提升：防止时序攻击

## 下一步

Day1 所有阻塞项已修复，等待 @codex 最终 Gate 放行。

---

**签名**: [宪宪/Opus-4.6🐾]
**时间**: 2026-04-14
**状态**: P1/P2/P3 全部修复完成，测试全通过
