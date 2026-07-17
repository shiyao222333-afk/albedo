# 代码审查 · 韧性层(空响应/截断/漂移) + 抖动根因（火眼眼, 2026-07-17）

> 受审对象：`core/llm.py`、`core/truth_track.py`、`core/salience.py`、`scripts/run_robustness_test.py`、`docs/DESIGN-RESILIENT-LLM-2026-07-16.md`、运行时日志 `data/out/robust_0.4.5.log`
> 审查目标：①代码是否正常工作 ②抖动是不是代码问题 ③B(组合频率门槛)是否落实 ④等待时的设计是否做了

---

## 直接回答你的 4 个问题（TL;DR）

| # | 问题 | 结论 |
|---|------|------|
| 1 | 代码是不是正常工作 | ✅ 基本正常（编译通过、单测全过）；发现 1 个效率 bug + 1 个设计张力（非崩溃类） |
| 2 | 抖动是不是代码问题 | ❌ **不是 B 的代码 bug**。B 实现正确；抖动来自「DeepSeek 温度=0 不严格」+「你用 `--no-cache` 跑了 3 次独立重抽」→ B 只在【单次调用内】去噪，跨 3 次独立调用压不住 |
| 3 | 本轮结果只有 A 的，B 落实了吗 | ✅ **B 已落实**（`truth_track.py` L170-272 对策3，有单测）。你感觉「只有 A 的效果」是因为 `--no-cache` 下 B 的跨轮收益看不见 |
| 4 | 等待时做的设计做了吗 | ✅ **做了**（`DESIGN-RESILIENT-LLM-2026-07-16.md`，125 行，根因/对策/验证计划/待拍板齐全） |

---

## 审查总览（火眼眼）

**整体印象**：架构合理。韧性层三对策（空响应重试 / 续写游标 / 频率门槛并集）都已落地、单测通过、思路科学。最危险的是——**设计文档和 CHANGELOG 对 B 的「跨轮收敛」预期表述过重，和测试实际行为不符**，容易让人误以为 B 写错了（其实没写错）。

**抖动根因（实锤，来自运行时日志）**：
- 测试用 `use_cache=False`（log L15）→ `refine()` 跑了 3 次**独立**重抽。
- 结果：RUN1=3/suspect、RUN2=5/true、RUN3=3/suspect；trust 恒 0.42，但 label 翻转。
- 3 次都稳定出现的核心主张：`今天给大家带来MC新版本介绍 / 然后这是一个遗憾 / 那么这个就是它带来了一个问题` —— **这正是 B 频率门槛留下的（≥2/3 出现）**。
- 漂移只发生在「额外几条」：RUN2 多 2 条、RUN3 多 2 条且各不相同（log L81）。这些额外条是 **豁免路径（factual+public+check_worthy 仅出现 1 次也留）** + **个别页被截断丢弃**导致的。
- 结论：**B 在单次调用内工作正确、核心主张已稳定；抖动是豁免-1次主张 + 页丢弃 + 模型方差在「3 次独立调用」下放大**的结果，不是 B 的代码缺陷。

---

## 🔴 Blockers（必须修）
无。未发现数据损坏、安全漏洞、崩溃类问题。

## 🟡 Suggestions（应该修）

**S1 · 截断响应被当瞬时故障，浪费 3 次完整调用（真效率 bug）**
`core/llm.py` 的 `call_llm` 只检查 `content.strip()` 为空才抛 `EmptyResponseError`（L80-85）。对 **`finish_reason=length` 的非空截断响应**，它返回部分 JSON → `extract_json_block` 返 None → `call_llm_json` 指数退避**重试 3 次完整调用**，第 3 次失败后 `_extract_one_page` 才走续写游标。
证据：log 中 `finish_reason=length` 反复出现 + L47/L61/L64/L65 多次「已重试 3 次」「抽取失败，丢弃该页」。
**建议**：`call_llm` 检测 `finish_reason == "length"` 且内容非空时，抛 `TruncatedResponseError`（或 `call_llm_json` 在 `extract_json_block is None` 且 `finish=="length"` 时直接 signal 续写），省掉 2-3 次无效完整调用、降低丢页率。

**S2 · B 的「跨轮收敛」预期与测试行为不符（文档/CHANGELOG 夸大）**
- 设计文档 L112-115：要求 B 让「3 轮收敛到同一数值，不再 2/4/5」。
- CHANGELOG [0.4.5]：称 B「治三轮主张漂移(2/4/5)」。
- 但 B 只在**单次** `extract_claims_self_consistent` 调用的 n=3 抽样内去噪；`--no-cache` 下 3 次独立调用，B 无法跨调用稳定。
**建议**：二选一 —— ①改验证方式：鲁棒性测试**默认带 cache**（脚本 docstring L10 本就写「2/3 次命中缓存不重抽」），那时 run2/3 载入缓存主张，B 的「单次内稳定」自然延伸到跨轮，应 PASS；②或明确文档：B 只治「单次内漂移」，跨轮稳定交给 CE4 缓存 / seed（即任务 #141）。

**S3 · 豁免路径在独立调用下反而增加跨轮方差（设计张力）**
`_is_exempt`（L244-255）让 `factual+public+check_worthy` 仅出现 1 次也保留。设计意图好（不放行高 stakes 主张被误杀），但在 **`--no-cache` 独立调用**下，这些「1 次主张」每次抽到的都不一样 → 跨轮 extras 漂移（log L81 即此）。
**建议**：豁免主张也要求 ≥2 次出现，或跨轮统一用缓存固定；否则 B 的稳定性收益被自身豁免路径吃掉一半。

## 💭 Nits（锦上添花）

- **N1（#146 重复行）**：`truth_track.py` L200-201 两行 `n = max(1, n_samples)` 重复，删一行。
- **N2（文档轻微过期）**：设计文档 L13-16 仍贴「第 69 行不检查 content」旧代码片段，实际已改为 L80-85。代码已对，仅文档示例过期，可更新。

---

## 👍 值得肯定的地方（Praise）

- **CE0 时间桶覆盖**（v0.4.6）：最小爆炸半径（只改覆盖策略，权重不动），单测同步改断言，干净。
- **续写游标（resume cursor）**：`raw_decode` 提取已完成对象 + 「从最后 claim_id 续写」设计优雅，严守「绝不抬高 max_tokens 上限」原则（"Raising max_tokens blindly just moves the cliff"）。
- **频率门槛 + 组合豁免**：self-consistency 用频率滤波而非投票，科学且契合「禁用判定投票」约束。
- **EmptyResponseError 区分瞬时故障 vs 业务结果**：方向完全正确。

---

## 下一步（Next Steps）

1. **你拍板 #141（治抖动正解）**：①CE4 缓存天然固定（重跑鲁棒性测试**不带** `--no-cache`，run2/3 命中缓存即稳定）②传固定 seed ③接受方差 + 结论层更稳。
2. **S1 截断浪费可顺手修**（不阻塞主流程，能降丢页率、省 key）。
3. **建议重跑验证用默认 cache**：那时 B 的「单次内稳定」会自然延伸到跨轮，预计 `RESULT: PASS`（脚本自身 docstring 的设计意图就是如此）。
4. #142/#143/#144/#145 仍待你拍板（见上一轮总览文件 OVERVIEW-CE0-AUDIT-2026-07-16.md）。
