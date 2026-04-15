# F001: Wiki Engine v1 Core

**Status**: ✅ done
**Owner**: @opus
**Created**: 2026-04-14
**Completed**: 2026-04-15

## 愿景

实现一个 MCP 协议的 Wiki 引擎，支持 Agent 安全地读写知识库，具备完整的审批流程、审计追踪和索引管理。

## 范围

### 已完成

**Day1: 基础设施**
- Lock Manager（文件锁 + 超时清理）
- ACL（审批人权限管理）
- Schema（frontmatter 校验）
- Commit: c8bec6f

**Day2: Workflow Engine**
- propose→lint→apply 三阶段流程
- 签名验证 + TOCTOU 检查
- 审计日志
- Commit: 6f7d53e, 1794d93, bfde294

**Day3: 索引与影子评估**
- IndexManager（append-only + 周期性压缩）
- ShadowEvaluator（规则引擎预测自动审批）
- Commit: eabd4ef

**Day3.1: 补强**
- 页面路径解析修复
- 并发保护增强
- 失败语义改进
- Commit: 439cf39

**Day4: MCP Tools Layer**
- 5 个工具函数：wiki_read/status/search/propose_patch/apply_patch
- 17 个 contract tests
- 错误码透传设计
- Commit: 54807a8

**Day5: MCP Server Layer**
- JSON-RPC stdio 协议实现
- Content-Length framing
- 参数校验
- 11 个 server contract tests
- P0/P1/P2 修复完成
- Commit: 7545cc7, 913c963, 7e590af

### 测试覆盖

**全量测试**: 73/73 passed
- ACL: 5/5 ✓
- Index Manager: 3/3 ✓
- Lint: 5/5 ✓
- Lock Concurrent: 2/2 ✓
- Lock Manager: 4/4 ✓
- MCP Server: 12/12 ✓
- MCP Tools: 27/27 ✓
- Shadow Evaluator: 4/4 ✓
- Workflow: 11/11 ✓

## 架构决策

### ADR-001: 三阶段工作流
- propose: 提议变更，运行 lint，保存到 .pending/
- lint: 校验 frontmatter schema 和业务规则
- apply: 验证签名，检查 TOCTOU，应用变更

### ADR-002: Append-only 索引
- 操作日志追加到 index.ops.jsonl
- 周期性压缩到 wiki/index.md
- 并发安全（flock）

### ADR-003: 影子评估
- 规则引擎预测未来自动审批可行性
- 不影响当前审批流程
- 为后续自动化提供数据

### ADR-004: 透传语义
- MCP Tools 层直接透传 Workflow 返回值
- 不做错误码归一化
- 保持一致性

### ADR-005: 零依赖 JSON-RPC
- 手写 JSON-RPC 子集
- 只实现 initialize / tools/list / tools/call
- 避免外部依赖

## v1 完整能力（已全部实现）

**11 个 MCP 工具**：
- ✅ `wiki_read` - 读取页面
- ✅ `wiki_status` - Wiki 状态统计
- ✅ `wiki_search` - 全文搜索
- ✅ `wiki_propose_patch` - 提议变更
- ✅ `wiki_apply_patch` - 应用变更
- ✅ `wiki_graph_neighbors` - 知识图谱邻居查询
- ✅ `wiki_ingest` - 源文档摄入
- ✅ `wiki_list_conflicts` - 冲突列表
- ✅ `wiki_resolve_conflict` - 冲突解决
- ✅ `wiki_lint` - 独立 lint 工具
- ✅ `wiki_rollback` - 回滚变更

**测试覆盖**：73/73 passed
- MCP Tools: 27 个测试（覆盖所有 11 个工具）
- MCP Server: 12 个测试（协议层 + 工具调用）
- Workflow: 11 个测试
- 其他模块: 23 个测试

## 未完成范围（v2 候选）

**端到端集成测试**：
- Claude Desktop 客户端连接测试
- 完整 propose→apply 流程验证

**文档完善**：
- 部署指南（如何配置 Claude Desktop）
- API 参考文档

## 交付物

**代码**：
- `wiki_engine/` - 核心引擎
- `tests/` - 62 个测试用例
- `docs/` - 设计文档和交付总结

**文档**：
- `docs/DAY1_DELIVERY.md` - Day1 交付
- `docs/DAY2_GATE_FIXES_ROUND2.md` - Day2 修复
- `docs/DAY3_DELIVERY.md` - Day3 交付
- `docs/DAY4_PLAN.md` - Day4 计划
- `docs/DAY5_DELIVERY.md` - Day5 交付

**Commits**：
- c8bec6f - Day1
- 6f7d53e - Day2
- 1794d93 - Day2 gate 修复
- bfde294 - Day2 gate P0 修复
- eabd4ef - Day3
- 439cf39 - Day3.1 补强
- 54807a8 - Day4
- 7545cc7 - Day5 初版
- 913c963 - Day5 P0 修复
- 7e590af - Day5 P1/P2 修复

## 验收标准

- [x] 全量测试通过（62/62）
- [x] @codex 复审通过
- [x] 代码已推送到远端
- [x] 文档完整（Day1-5 交付总结）
- [x] 无阻断问题

## 签名

[宪宪/Opus-4.6🐾]
2026-04-15
