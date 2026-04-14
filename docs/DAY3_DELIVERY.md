# Day3 交付总结

**Date**: 2026-04-14
**Status**: ✅ 完成

## 交付状态：✅ 全部完成

### 核心交付：Index Manager + Shadow Evaluator

**交付物：**
- `wiki_engine/index_manager.py` - 索引管理器（append-only + 压缩）
- `wiki_engine/shadow_evaluator.py` - 影子评估器（规则引擎）
- `tests/test_index_manager.py` - 2 个测试用例
- `tests/test_shadow_evaluator.py` - 4 个测试用例
- Workflow 集成 + 2 个集成测试

## 1. Index Manager 实现 ✅

### 核心特性

**Append-only 操作日志：**
- 所有索引操作写入 `.index/index.ops.jsonl`
- 每条操作包含：op_id, timestamp, operation, page_id, title, summary, category
- 支持操作类型：add, update, remove

**周期性压缩：**
- 触发条件：
  - 操作数达到阈值（默认 100 条）
  - 或距上次压缩超过时间间隔（默认 24 小时）
- 压缩逻辑：
  - 重放所有操作，构建最终状态
  - 生成 `wiki/index.md`（按 category 分组）
  - 清空 `index.ops.jsonl`
  - 记录压缩时间到 `meta.json`

**自动元数据提取：**
- 从页面 frontmatter 提取 title, category
- 从页面正文提取 summary（首个非标题段落，最多 180 字符）
- 支持 YAML frontmatter 解析

### 接口

```python
class IndexManager:
    def record_patch(self, patch: Patch):
        """从 patch 记录索引操作"""

    def append_operation(self, op: IndexOperation):
        """追加单条操作到 index.ops.jsonl"""

    def should_compact(self) -> bool:
        """判断是否需要压缩"""

    def compact(self):
        """执行压缩：重放操作 -> 生成 index.md"""
```

### 生成的 index.md 格式

```markdown
---
generated_at: 1713074400.0
total_pages: 5
---

# Wiki Index

## Category: concepts

- [page-1](page-1.md) - Summary of page 1
- [page-2](page-2.md) - Summary of page 2

## Category: entities

- [entity-1](entity-1.md) - Summary of entity 1
```

## 2. Shadow Evaluator 实现 ✅

### 核心特性

**规则引擎：**
- 基于 operation, confidence, source_refs, diff_size 评估
- 输出 4 个维度：
  - `would_auto_apply`: 是否可自动审批（布尔值）
  - `reason`: 决策原因（字符串）
  - `risk_level`: 风险等级（low/medium/high）
  - `score`: 综合评分（0.0-1.0）

**评估规则（v1）：**

1. **Delete 操作**：永远需要人工审批
   - `would_auto_apply = False`
   - `reason = "delete_requires_manual_review"`
   - `risk_level = "high"`

2. **Create 操作**：高置信度可自动审批
   - 条件：`confidence >= 0.95` AND `len(source_refs) >= 1`
   - `would_auto_apply = True`
   - `reason = "high_confidence_create"`
   - `risk_level = "low"`

3. **Update 操作**：严格条件下可自动审批
   - 条件：`confidence >= 0.98` AND `len(source_refs) >= 2` AND `diff_len <= 600`
   - `would_auto_apply = True`
   - `reason = "high_confidence_small_update"`
   - `risk_level = "medium"`

4. **其他情况**：需要人工审批
   - `would_auto_apply = False`
   - `reason = "requires_human_review"`

**评分算法：**
```python
score = 0.65 * confidence
      + 0.20 * min(1.0, source_ref_count / 3.0)
      + 0.15 * normalized_diff_size
```

### 接口

```python
class ShadowEvaluator:
    def evaluate_patch(
        self,
        operation: str,
        confidence: float,
        source_refs: list[str],
        affected_pages: list[str],
        diff_content: str,
    ) -> ShadowEvalResult
```

### 设计理念

**为什么叫 "Shadow"？**
- v1 保持人工审批流程不变
- Shadow Evaluator 在后台运行，记录"如果自动化会怎样"
- 积累数据用于未来决策：
  - 哪些规则准确率高？
  - 哪些场景可以安全自动化？
  - 人工审批与预测的差异在哪里？

**渐进式信任：**
- 不是一步到位的自动化
- 先观察、积累数据、验证规则
- 基于数据而非假设做决策

## 3. Workflow 集成 ✅

### propose_patch 集成

```python
def propose_patch(...) -> dict:
    # ... 原有逻辑 ...

    # 运行 shadow evaluation
    shadow_eval = self.shadow_evaluator.evaluate_patch(
        operation=operation,
        confidence=confidence,
        source_refs=sources,
        affected_pages=pages,
        diff_content=diff
    )

    # 保存到 patch 数据
    patch = Patch(
        ...,
        shadow_eval_result=shadow_eval.to_dict()
    )
```

### apply_patch 集成

```python
def apply_patch(...) -> dict:
    # ... 原有逻辑 ...

    # 成功 apply 后记录索引操作
    self.index_manager.record_patch(patch)

    return {
        "status": "success",
        "change_id": change_id,
        ...
    }
```

### Patch 数据结构更新

```python
@dataclass
class Patch:
    patch_id: str
    agent_id: str
    operation: str
    affected_pages: List[str]
    diff_content: str
    confidence: float
    source_refs: List[str]
    base_commit: str
    lint_status: str
    lint_errors: Optional[List]
    shadow_eval_result: Optional[Dict]  # 新增字段
```

## 测试覆盖

### IndexManager 测试（2 个）

1. `test_replay_and_compaction`
   - 验证操作重放逻辑
   - 验证压缩生成 index.md
   - 验证 remove 操作正确处理

2. `test_record_patch_appends_ops`
   - 验证从 patch 记录操作
   - 验证多页面 patch 生成多条操作

### ShadowEvaluator 测试（4 个）

1. `test_high_confidence_create_can_auto_apply`
   - 验证高置信度 create 可自动审批

2. `test_delete_always_requires_manual_review`
   - 验证 delete 永远需要人工审批

3. `test_update_auto_apply_rule`
   - 验证 update 自动审批规则

4. `test_low_confidence_update_stays_manual`
   - 验证低置信度 update 需要人工审批

### Workflow 集成测试（2 个）

1. `test_propose_patch_update_existing_page_runs_real_lint`
   - 回归测试：update 操作调用真实 linter
   - 验证不会崩溃（Day2 修复的问题）

2. `test_apply_patch_records_shadow_eval_and_index_ops`
   - 验证 propose 时记录 shadow_eval_result
   - 验证 apply 成功后写入 index.ops.jsonl

### 全套测试结果

```
31/31 passed in 2.56s

- ACL: 5/5 ✓
- Index Manager: 2/2 ✓
- Lint: 5/5 ✓
- Lock Concurrent: 2/2 ✓
- Lock Manager: 4/4 ✓
- Shadow Evaluator: 4/4 ✓
- Workflow: 9/9 ✓
```

## 关键设计决策

### ADR-007: 为什么 Index Manager 用 append-only？

**决策**：索引操作先追加到 `.index/index.ops.jsonl`，定期压缩到 `wiki/index.md`

**理由**：
1. **性能**：追加操作 O(1)，无需每次重新生成整个索引
2. **可审计**：保留完整操作历史（压缩前）
3. **容错**：压缩失败不影响操作记录
4. **并发友好**：追加操作冲突概率低

**权衡**：
- 优点：快速、可靠、可审计
- 缺点：需要定期压缩，增加复杂度
- 选择：复杂度可控，收益明显

### ADR-008: 为什么 Shadow Evaluator 不直接自动化？

**决策**：v1 只预测，不执行；保持人工审批流程

**理由**：
1. **安全第一**：知识库修改风险高，需要人工把关
2. **数据驱动**：先积累数据，验证规则准确性
3. **渐进式信任**：基于实际表现逐步放开自动化
4. **可回退**：发现问题可以立即停止，不影响现有流程

**未来演进路径**：
- Phase 1（当前）：Shadow mode，只记录预测
- Phase 2：部分自动化（低风险操作）
- Phase 3：基于数据调整规则
- Phase 4：扩大自动化范围

### ADR-009: 为什么 Index Manager 从页面提取元数据？

**决策**：从页面 frontmatter 和正文自动提取 title, summary, category

**理由**：
1. **单一真相源**：页面内容是唯一真相源，索引是派生数据
2. **自动同步**：页面更新时自动更新索引，无需手动维护
3. **容错**：即使索引损坏，可以从页面重建

**权衡**：
- 优点：自动化、一致性、可重建
- 缺点：需要解析 frontmatter，增加复杂度
- 选择：复杂度可控，收益明显

## 接口规范更新

### propose_patch 返回值增强

```python
{
    "status": "success",
    "patch_id": "patch-20260414-123456",
    "requires_approval": true,
    "confidence": 0.95,
    "lint_status": "passed",
    "lint_errors": null,
    "shadow_eval": {  # 新增字段（内部使用，不暴露给 MCP）
        "would_auto_apply": true,
        "reason": "high_confidence_create",
        "risk_level": "low",
        "score": 0.8765
    }
}
```

**注意**：`shadow_eval` 字段仅用于内部记录和分析，不暴露给 MCP 接口（按照 Day1 设计）。

## 下一步（Day4-7）

按照原计划：
- ✅ Day1: Lock Manager + ACL + Schema
- ✅ Day2: Workflow Engine (propose->lint->apply)
- ✅ Day3: Index Manager + Shadow Evaluator
- 🔜 Day4-7: MCP 接口实现

Day3 完成，可以进入 MCP 接口开发阶段。

---

**签名**: [宪宪/Opus-4.6🐾]
**时间**: 2026-04-14
**Commit**: eabd4ef
**测试**: 31/31 passed
