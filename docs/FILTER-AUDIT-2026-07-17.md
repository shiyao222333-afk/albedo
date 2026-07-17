# 过滤器误伤不可感知 — 盘点与修复（v0.4.9 F 任务）

> 用户关切：硬删过滤器把"不符合的"过滤掉没问题，但把"符合的"也删了却**看不见**，无法发现误杀。
> 结论：已给所有硬删过滤器加**审计留痕**（dropped_audit）——被删的主张原样保留 + 原因 + 阶段，报告里专门列出。

## 一、代码里所有"硬删 / 强制剔除"型过滤器盘点

| # | 位置 | 删什么 | 当前是否留痕 | 留痕程度 |
|---|------|--------|------------|---------|
| 1 | `truth_track._is_water_claim` + AE1 闸门（`truth_track.py` L838-846） | 水词/过渡句/定义碎片 + 非可证伪观点（check_worthy=False） | ❌ 仅 logger 计数 | **无内容留痕（盲点）** |
| 2 | `guard_claim_faithfulness` Layer0.5（`truth_track.py` L514-551） | 字幕无依据（防瞎编 NLI 裁决）的主张 | ❌ 仅返回 n_dropped 计数 | **无内容留痕（盲点）** |
| 3 | `faithfulness_check` CE3（`truth_track.py` L422-446） | 标记 grounded/ungrounded，**不硬删**；真正删除在 #2 | — | 标记不删 |
| 4 | `apply_sop_gate` AC4（`ground_extract.py` L188-222） | SOP 步骤中字幕无依据的编造项 | ✅ `_gate.reasons`（40字片段+原因码） | **部分留痕（有片段）** |
| 5 | `apply_flag_gate` AC5（`ground_extract.py` L233-262） | **不删**，只标 `_ungrounded` 保留供核对 | ✅ 完整保留 + 报告⚠️ | **最佳（软标记）** |
| 6 | `web_verify_claims` / `verify_claims_web` | 不删，结论降级 unverified | — | 降级不删 |

**核心盲点 = #1 + #2（主张线）**：之前只记"删了 N 条"，删掉的到底是哪些话、为什么删，完全看不到。

## 二、解决方法（已实施 = F 任务）

原则：**永远"隔离"而非"销毁"**。每条被硬删的主张都进 `dropped_audit` 列表：

```python
{"quote": "原话", "ts": "时间戳", "stage": "AE1_water|AE1_noncheckworthy|L0.5_ungrounded", "reason": "为什么删"}
```

- 写入链路：`_run_truth_track` 收集 → `aggregate()` 进 `truth_track` 字典 → `save_claim_cache` 冻结进缓存（复查也能看见）→ `report._render_truth_track` 渲染成 **🔍 被过滤主张（审计）** 章节。
- 报告里每条被删主张都列出「阶段 + 原话 + 原因」，并在章节头写明"如误杀请告诉我，我调阈值"。
- 用户（非程序员）现在能一眼看到"被删了哪些"，发现误杀直接告诉我，调阈值/改规则即可。
- 额外保险：缓存带 `verify_sig`，过滤器逻辑一变旧缓存自动失效（`claim_cache.compute_verify_sig`），不会让旧误杀"藏"在缓存里。

## 三、验证

- `tests/test_dropped_audit.py`：mock 掉 LLM，造 4 条主张（水词/观点/真事实有依据/真事实无依据），断言
  - 真事实 c2 必保留且不进审计；
  - 水词→`AE1_water`、观点→`AE1_noncheckworthy`、字幕无依据→`L0.5_ungrounded` 三条审计全中；
  - 每条审计带 reason + ts。✅ PASS
- 报告渲染实测：审计章节正确输出（见对话）。
- `py_compile` 三模块通过。

## 四、待办 / 注意事项

1. **B/C/D/E 端到端验证未跑成**：上一轮 `--shared-cache` 鲁棒性测试用的 `data/out/nigredo_BV1pQ7o61EMh.json` 是**空字幕**（subtitle_text/title 全空）→ 抽 0 条，没真正跑通管线。需真实字幕才能验 B/C/D/E（F 已用单测验过）。
2. **预存测试失败（非本次引入）**：`test_ce4_cache` / `test_cache_hit` 调 `save_claim_cache` 时不带 `verify_sig`，而 v0.4.7 的"无 sig 即失效"规则会让 load 返回 None。属 v0.4.7 引入的测试滞后，生产路径（始终带 sig）不受影响。
