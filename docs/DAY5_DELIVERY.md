# Day5 交付总结

**Date**: 2026-04-15
**Status**: ✅ 完成并通过 @codex 复审

## 交付状态：✅ 全部完成

### 核心交付：MCP Server Layer

**交付物：**
- `wiki_engine/mcp_server.py` - MCP Server 实现（JSON-RPC stdio）
- `tests/test_mcp_server.py` - 11 个 server contract tests
- P0/P1/P2 修复完成

## 1. MCP Server 实现 ✅

### 核心特性

**协议支持：**
- `initialize`: 协议握手，返回 server 能力声明
- `tools/list`: 列出 5 个可用工具
- `tools/call`: 调用工具并返回结果
- `serve_stdio`: Content-Length framed stdio 主循环

**5 个暴露工具：**
1. `wiki_read` - 读取页面内容
2. `wiki_status` - 获取 wiki 统计
3. `wiki_search` - 全文搜索
4. `wiki_propose_patch` - 提议变更
5. `wiki_apply_patch` - 应用变更

**设计决策：**
- 零第三方依赖：手写 JSON-RPC 子集
- 透传语义：直接调用 Day4 工具函数
- 标准 framing：Content-Length HTTP-style headers
- 参数校验：基于 inputSchema 的类型和约束检查

## 2. P0/P1/P2 修复历程 ✅

### 第一轮修复（P0）

**P0-1: MCP 标准 stdio framing**
- 问题：逐行 JSON 不兼容标准 MCP 客户端
- 修复：实现 Content-Length framing
- Commit: 913c963

**P0-2: 参数校验**
- 问题：声明了 inputSchema 但未执行校验
- 修复：新增 `_validate_arguments()` 方法
- Commit: 913c963

### 第二轮修复（P1/P2）

**P1: 多 header 支持**
- 问题：只读单个 Content-Length header，多 header 报文被丢弃
- 修复：循环读取所有 header 直到空行
- 复现：`Content-Length` + `Content-Type` 报文现在正确处理
- Commit: 7e590af

**P2: bool 类型校验**
- 问题：`isinstance(True, int)` 为真，bool 被误判为 integer
- 修复：显式排除 `isinstance(value, bool)`
- 复现：`wiki_search(limit=True)` 现在返回 -32602
- Commit: 7e590af

## 3. 测试覆盖 ✅

### 11 个 server contract tests

**协议测试：**
1. `test_initialize_returns_capabilities` - 初始化握手
2. `test_tools_list_contains_all_day4_tools` - 工具列表完整性

**工具调用测试：**
3. `test_tools_call_wiki_read_success` - 成功调用
4. `test_tools_call_unknown_tool_returns_error` - 未知工具错误
5. `test_tools_call_invalid_arguments_type_returns_error` - 参数类型错误

**Framing 测试：**
6. `test_serve_stdio_handles_parse_error_and_valid_request` - Parse error 容错
7. `test_serve_stdio_with_content_length_framing` - 标准 framing
8. `test_serve_stdio_with_multiple_headers` - 多 header 支持（P1）
9. `test_serve_stdio_notification_no_response` - Notification 不回包

**参数校验测试：**
10. `test_tools_call_validates_minimum_constraint` - minimum 约束（P0-2）
11. `test_tools_call_rejects_bool_as_integer` - bool 类型拒绝（P2）

### 全量测试结果

```
62/62 passed in 4.14s

- ACL: 5/5 ✓
- Index Manager: 3/3 ✓
- Lint: 5/5 ✓
- Lock Concurrent: 2/2 ✓
- Lock Manager: 4/4 ✓
- MCP Server: 11/11 ✓
- MCP Tools: 17/17 ✓
- Shadow Evaluator: 4/4 ✓
- Workflow: 11/11 ✓
```

## 关键设计决策

### ADR-010: 为什么手写 JSON-RPC 而不用第三方库？

**决策**：手写 JSON-RPC 子集，只实现 initialize / tools/list / tools/call

**理由**：
1. **零依赖**：避免外部包缺失阻塞开发
2. **可控性**：精确控制协议行为，便于调试
3. **轻量级**：只需 3 个方法，引入完整库过重
4. **透明性**：代码简单直接，易于理解和维护

**权衡**：
- 优点：无依赖、可控、轻量
- 缺点：不支持完整 JSON-RPC 2.0 规范（如 batch requests）
- 选择：当前需求只需 3 个方法，手写足够

### ADR-011: 为什么参数校验在 MCP 层而不是工具层？

**决策**：在 `_handle_tool_call` 中基于 inputSchema 校验参数

**理由**：
1. **契约一致性**：MCP 声明了 inputSchema，必须执行校验
2. **快速失败**：在协议层拒绝无效参数，避免进入业务逻辑
3. **错误码标准化**：统一返回 -32602 Invalid params
4. **分层清晰**：协议层负责协议合规，工具层负责业务逻辑

**权衡**：
- 优点：契约一致、快速失败、标准化
- 缺点：增加 MCP 层复杂度
- 选择：契约一致性优先级更高

### ADR-012: 为什么支持多 header 而不只是 Content-Length？

**决策**：循环读取所有 header 直到空行，兼容多 header 报文

**理由**：
1. **标准兼容性**：HTTP-style framing 允许多 header
2. **客户端多样性**：不同 MCP 客户端可能发送 Content-Type 等额外 header
3. **鲁棒性**：不因额外 header 导致请求被丢弃
4. **未来扩展**：为可能的协议扩展预留空间

**权衡**：
- 优点：标准兼容、鲁棒、可扩展
- 缺点：略微增加解析复杂度
- 选择：兼容性优先级更高

## 接口规范

### serve_stdio 协议

**输入格式（Content-Length framing）：**
```
Content-Length: 123\r\n
Content-Type: application/json\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

**输出格式：**
```
Content-Length: 456\r\n
\r\n
{"jsonrpc":"2.0","id":1,"result":{"tools":[...]}}
```

**特殊处理：**
- Notification（无 id 字段）：不回包
- Parse error：返回 -32700
- Invalid request：返回 -32600

### 参数校验规则

**支持的校验：**
- `type`: string / integer / number / array / object
- `required`: 必填字段检查
- `minimum`: 数值最小值约束
- `additionalProperties`: 额外字段检查

**特殊处理：**
- `bool` 类型：显式排除，不被误判为 integer/number
- 违反约束：返回 -32602 Invalid params

## 残余风险（非阻断）

**@codex 提到的非阻断风险：**
- 小写 `content-length` header 兼容性未测试
- 建议后续补充测试用例

**规则一致性：**
- `confidence=0.9` 语义需要文档化
- 避免后续实现漂移

## 下一步

Day5 完成，可选方向：

1. **v1 能力补齐**（6 个未实现工具）：
   - `wiki_graph_neighbors` - 知识图谱邻居查询
   - `wiki_ingest` - 源文档摄入
   - `wiki_list_conflicts` - 冲突列表
   - `wiki_resolve_conflict` - 冲突解决
   - `wiki_lint` - 独立 lint 工具
   - `wiki_rollback` - 回滚变更

2. **端到端集成测试**：
   - Claude Desktop 客户端连接测试
   - 完整 propose→apply 流程验证

3. **文档完善**：
   - 部署指南（如何配置 Claude Desktop）
   - API 参考文档

---

**签名**: [宪宪/Opus-4.6🐾]
**时间**: 2026-04-15
**Commits**: 7545cc7 (初版), 913c963 (P0 修复), 7e590af (P1/P2 修复)
**测试**: 62/62 passed
**复审**: @codex PASS
