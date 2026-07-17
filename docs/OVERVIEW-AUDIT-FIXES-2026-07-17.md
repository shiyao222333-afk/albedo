# 炼真 Albedo · 审计修复批次 + B 就绪（v0.4.6.x）

> 日期：2026-07-17｜对应指令：小问题顺手修 + 把 B 准备好 + 下次测试前做完未完成的
> 状态：代码修复全部落地，7 个单测全 PASS；带缓存鲁棒性测试后台运行中（验证 B）

---

## 一、小问题（顺手修）

| 项 | 文件 | 改动 |
|---|---|---|
| #146 重复行 | `core/truth_track.py` L200-201 | `n = max(1, n_samples)` 误写两遍，删一行 |
| S1 截断浪费重试 | `core/llm.py` | 新增 `TruncatedResponseError`；`call_llm` 在 `finish_reason=='length'` 抛出，`call_llm_json` 直接 re-raise → 直走续写游标，不再 3 次整页重试（省 key + 降丢页率） |
| N2/S2 文档夸大 | `docs/DESIGN-RESILIENT-LLM`、`CHANGELOG` | 过期行号改正；明确「B 只在单次调用内去噪，跨调用靠缓存冻结」 |

---

## 二、审计发现的静默问题（#142–#145）

| 任务 | 问题 | 修复 |
|---|---|---|
| **#142** CE3 硬删 × prompt 矛盾 | `faithfulness_check` 子串未命中直接硬删，但抽主张提示词允许「微调措辞」→ 忠实改写主张被误删（假阴性） | CE3 改为**只标记** `grounded/ungrounded`，不删；最终去留交 Layer0.5 guard 的 LLM NLI 裁决 |
| **#143** guard 默认放水 | `guard_claim_faithfulness` 对 guard 未覆盖的 claim 默认 `supported=True` 放行 → 长视频截断后幻觉被静默放过 | guard 未覆盖的 claim **回退 CE3 确定性子串判定**（`sup = faithfulness=="grounded"`）；LLM NLI 为权威裁决（不误杀也不放水） |
| **#145** 信任分反转 | `aggregate` 中 `personal/opinion=0.55 > factual+public=0.50`，与「可证伪公开事实更可信」语义相反 | 改为 personal/opinion→**0.5**，factual+public→**0.6**（上限 0.6） |
| **#144** 结论层未受韧性覆盖 | 核验 `refine()` → `judge_document`（纯 numpy D-S 融合，同输入必同结论）。翻转根因是**输入主张随独立重抽变化**，非结论算法不稳 | **无需改判定代码**，靠 #141 缓存冻结主张集解决 |

---

## 三、B 准备好（#141 跨调用漂移根治）

**根因再确认**：审计时已确认 B（组合频率门槛）代码正确，抖动来自
1. DeepSeek 即便 `temperature=0` 也不严格可复现（模型方差）；
2. 上次测试用 `--no-cache`，等于把同视频**独立重抽 3 次**；
3. **隐藏根因**：测试脚本 `load_input` 在字幕 JSON 缺 `video_id` 时传空串 → 缓存函数对空 `video_id` 直接返回 None → **缓存根本没生效**。

**本轮回应的真正修复**：把 CE4 缓存从「只冻抽取」升级为「冻结最终主张集」
- `save_claim_cache` 从 CE3 后移到 **guard + Layer1~Layer3 全部完成后**；
- 缓存命中时**跳过抽取/guard/各层**，直接复用最终主张集 → 复查 = 完全确定性复现；
- 测试脚本在 JSON 缺 `video_id` 时**从文件名推导 BV 号**，确保缓存生效。

> 这是「同视频三次不一样」的真正根治。B 仍在场（单次调用内去噪），缓存负责跨调用稳定。

---

## 四、验证

- ✅ `py_compile` 全绿（`llm/truth_track/claim_cache/run_robustness_test`）
- ✅ `tests/test_claim_stability.py` **7/7 PASS**（CE0 时间桶 / CE1+CE2 频率门槛 / CE3 标记不删 / **新增 guard 回退 CE3 ×2** / CE4 缓存）
- ⏳ 带缓存鲁棒性测试后台运行中：`run_robustness_test.py data/BV1h1LD6BELK_subs.json` → `data/out/robust_v046.log`
  - 预期：`claim_quotes` 三轮一致、`truth_label` 稳定（B 经缓存显形）
  - task_id：`ykBuO4`

---

## 五、待办

- [ ] 后台测试出结果后确认 PASS，必要时排查（form_track 等非缓存层若仍波动，属已知独立问题）
- [ ] **全部改动仍未 git 提交**（v0.4.3 + v0.4.5 + v0.4.6 累计），待 L4 验收通过后统一 commit+push
