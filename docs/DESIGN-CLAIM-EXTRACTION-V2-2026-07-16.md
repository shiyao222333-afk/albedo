# 抽主张稳定性：科学方案 V2（截断 + 漂移根治）

> 日期：2026-07-16 ｜ 基于业界/学界实践调研，回应"自动加 max_tokens 不科学"的质疑
> 关联：`DESIGN-CLAIM-EXTRACTION-2026-07-16.md`（v0.4.3 自一致性重建）、`core/truth_track.py`、`core/llm.py`

## 0. 问题复盘

v0.4.3 自一致性重建后真实 3× 测试（BV1h1LD6BELK, --no-cache）：

| 指标 | 结果 |
|---|---|
| 真实性结论 | suspect / suspect / suspect ✅ 稳定（v0.4.4 基线 false/true 翻车已消失） |
| 主张数 | 2 / 4 / 5 ❌ 漂移（上一轮"11/11/11"是 refine() 缓存 bug 导致的缓存命中假象） |

根因：删掉"补括号 + 预算自动递增"救援后，DeepSeek 在 `json_object` 模式下仍因 `max_tokens=2048` 触顶而截断整批 JSON → 现直接丢弃整批 → 丢哪批随机 → 主张数漂移。旧那套虽丑但能"救回截断批次"→ 主张更全。

## 1. 别人怎么做（调研结论）

### 1.1 截断（输出过长被切断）
- **DeepSeek 支持 `json_schema` + `strict: true`**（比 `json_object` 强得多）：强制模型输出符合预设结构，从根上消灭"JSON 写一半 / 格式错"的解析失败（业界称为 constrained decoding，把畸形输出从误差预算里移除）。
- **但严格模式 ≠ 不会被截断**：DeepSeek 官方文档明写——`max_tokens` 太小、输出触顶仍会 `finish_reason="length"` 截断。所以换模式只是第一层，还需长度治理。
- **业界标准做法（非魔法数字、非无限加）**：
  1. **分页抽取（pagination）**：一次只抽 ≤5 条（page_size=5），多批抽、最后合并。长数组本就该这么拆（juejin / thrivewithai 生产实践）。
  2. **按结构算预算**：`max_tokens = estimate_output_tokens(schema, list_length=page_size) × 1.2 安全系数`——有公式、确定、封顶。
  3. **真截断就"接着写"（continuation）**：检测到 `finish_reason="length"`，让模型"从断点继续写完这个 JSON 数组"（同一页预算），不是盲目加大上限。仍不行才诚实丢弃该页并记日志（极少）。

### 1.2 不稳定（每轮主张不同）
- **自一致性（self-consistency, 抽 N 次聚合）是学界公认方法**（Wang 2022；多篇 2026 工程治理文）。
- **关键修正（比纯并集科学）**：
  - **频率门槛并集**：只保留在 N 次抽样中出现 ≥k 次（如 ≥2/3）的主张，一次性幻觉主张被滤掉。纯并集会把幻觉也留着。
  - **自一致性只抓"随机"飘，抓不了"系统性"错**——必须配合"溯源核对"（我们已有 CE3 faithfulness + MiniCheck Layer2）。研究明确两者要组合。
  - **N=5 是性价比甜点**；N=3 偶尔漏；高风险用 7。我们现 N=3，可升 5。
- **温度 0 注意**：研究指出 temp=0 下"投票式"自一致性失效（每样本同答），但我们用的是"并集/频率"而非投票，且 DeepSeek 实测 temp=0 仍非确定（GPU 浮点非结合性），故抽样仍有多样性，自一致性有效。

### 1.3 生产事实验证范式（我们的架构已对齐）
claim extraction(structured) → per-claim NLI/源核对 → 标低置信（blacksparc / how2.sh）。我们 = extract → CE3 溯源 → MiniCheck(Layer2) → web(Layer3)，结构正确，只需把 extraction 稳定住。

## 2. Albedo 具体方案

### A. 截断（输出长度）——预防性 + 有界
- **A1**：`response_format` 从 `json_object` 升级为 `json_schema` + `strict: true`，预设紧的 Claim 结构（每条固定短字段：quote/ts/factuality/scope/check_worthy/hedge）。
- **A2**：`extract_claims_self_consistent` 改**分页**，每页 ≤5 条，循环抽、跨页+跨 N 次并集。
- **A3**：`max_tokens = page_size × ~220 × 1.2`（≈1320），按结构算、封顶、绝不无限加。
- **A4**：`finish_reason=="length"` → 该页"断点续写"（同预算 1 次）；仍截断 → 诚实丢该页 + 记日志（极少）。

### B. 不稳定（主张漂移）——频率门槛
- **B1**：保留 N=3（或升 5）抽样；聚合从纯并集改为**频率门槛并集**：仅在 ≥ceil(N/2) 次出现的主张进最终集；一次性主张丢弃。
- **B2**：继续 CE3 溯源 + MiniCheck 兜底（抓系统性错）。

### C.（可选）覆盖检查
- **C1**：抽完加一次便宜"查漏"调用："源里还有无值得查的主张你没抽出来？"→ 补回分页/截断漏掉的主张。比"盲目加大预算"科学。

## 3. 代码改动点（待用户拍板后实施）
- `core/llm.py`：`call_llm_json` 支持 `json_schema`(strict) 入参；`extract_json_block` 过时注释（"预算递增确保不截断"）删除。
- `core/truth_track.py`：`extract_claims_self_consistent` → 分页(5/页) + 频率门槛并集(≥2/3) + 续写兜底；常量 `PAGE_SIZE=5`、`CONSISTENCY_MIN=2`。
- 测试：`run_robustness_test.py` 复用；重跑验证主张集也稳定。

## 4. 验收
- 真实 3× (--no-cache)：主张数稳定（如 5/5/5 或小幅波动）+ 结论 suspect×3 + MiniCheck Layer2 真验。
- 无"整批丢弃"导致的计数漂移；`finish_reason=length` 触发续写而非丢批。
