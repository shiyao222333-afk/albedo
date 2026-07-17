# 设计文档：LLM 调用韧性层（治"空响应 + 截断 + 漂移"）

> 日期：2026-07-16
> 背景：v0.4.3 抽主张重建（CE0–CE4）已落地，A 方案（分页 5 条/页 + 公式预算封顶）已实施。
> 问题：3× 鲁棒性测试（BV1h1LD6BELK）日志暴露 DeepSeek 仍偶发**返回空 content** 与**提前停止截断**，
>       导致大量页面被丢弃、主张数漂移（2/4/5）。本方案根治这三件事。
> 依据：WebSearch 5 篇生产级文章（掘金/Dev.to/CSDN/php.cn）+ DeepSeek 官方行为。

---

## 一、根因（代码级实锤）

### 根因 1：空响应 —— `core/llm.py` 旧版未检查 content（v0.4.5 已修复，v0.4.6 增补截断处理）
```python
return resp.json()["choices"][0]["message"]["content"]   # 直接返回，没检查空/截断
```
DeepSeek 在服务压力大时返回 **HTTP 200 + 空 content**（或 `finish_reason=null`）。
学界/业界实证（掘金"GPT-6发布前夜"）："DeepSeek 的超时不抛 TimeoutException，而是返回 200 + 空 content。
我最开始的错误处理只捕获异常，完全没有检查响应内容，导致空字符串被作为正常结果写入。"
→ 当前代码把空串当正常返回 → `extract_json_block("")` 返 None → 抛 RuntimeError（日志里"原始回复前200字: （空）"即此）。

### 根因 2：截断（提前停止）—— `json_object` 模式模型主动 stop
日志里 `"hedge_le` 截断在字段中间"。5 条主张输出 ~400 token，远未触 PAGE_TOKENS=1320 上限，
故非预算触顶，而是 **DeepSeek 在 json_object 模式下偶发提前停止**（finish_reason=stop 但内容不完整）。
这是模型层行为，分页/预算无法根治，需"续写兜底"。

> **v0.4.6 修正（S1）**：`call_llm` 现检测 `finish_reason=='length'` 抛 `TruncatedResponseError`，
> `call_llm_json` 对其直接 re-raise，交由 `_extract_one_page` 走续写游标——不再浪费 3 次整页重试才放弃。

### 根因 3：漂移 —— 全并集保留一次性主张
现 `extract_claims_self_consistent` 用 `seen` 集合"出现 1 次就留"（全并集）。
随机丢失的页/主张 + 随机幻觉主张都会被保留 → 主张集随运行漂移。

---

## 二、对策（科学，非蛮力）

### 对策 1：空响应检测 + 重试（治根因 1）—— 改 `core/llm.py`
新增异常类 `EmptyResponseError(RuntimeError)`。
`call_llm` 返回前增加：
```python
choice = resp.json()["choices"][0]
content = (choice.get("message") or {}).get("content") or ""
finish = choice.get("finish_reason")
if not content.strip():
    raise EmptyResponseError(f"DeepSeek 返回空 content (finish_reason={finish})")
return content
```
`call_llm_json` 改为 **max_retries=3 + 指数退避**（捕获 EmptyResponseError 与解析失败）：
```python
for attempt in range(max_retries):
    try:
        raw = call_llm(messages, max_tokens=budget, response_format=rf, **kwargs)
        data = extract_json_block(raw)
        if data is not None:
            return data
    except EmptyResponseError as e:
        last_err = str(e)
    except Exception as e:
        last_err = f"调用异常: {e}"
    if attempt < max_retries - 1:
        time.sleep(2 ** attempt)   # 1s, 2s
raise RuntimeError(f"LLM 空响应/解析失败（已重试 {max_retries} 次）。{last_err}")
```
文献依据（codango/dev.to）：空响应检测那一行"修了 70% 空响应事故"；重试+退避把空响应率从 2.3% 降到 0.04%。

### 对策 2：续写兜底（治根因 2，不抬高 max_tokens）—— 改 `core/truth_track.py` 的 `_extract_page`
检测 JSON 未闭合 → 用 `json.JSONDecoder().raw_decode` 提取已完成的完整主张对象 →
丢弃半截的 → 让模型"从最后一条 claim_id 继续写完这一页"（同预算、不重跑整页、不抬高上限）：
```python
def _extract_page(...):
    data = call_llm_json(...)                      # 对策1已含重试
    if data is not None:
        return data
    # 续写：尝试从截断处恢复已完成对象
    partial = _recover_complete_objects(raw)        # raw_decode 提取已完成对象
    if partial:
        resumed = call_llm_json([... continue after id {last_id} ...], max_tokens=PAGE_TOKENS)
        if resumed:
            return {"claims": partial + resumed.get("claims", [])}
    return None                                      # 仍失败才诚实丢页（极少）
```
文献依据（dev.to "Your LLM JSON Got Cut Off"）：raw_decode 提取已完成对象 + resume cursor（continue after id N）
是标准做法；"Raising max_tokens blindly just moves the cliff"——**绝不靠抬高上限**。

### 对策 3：B 频率门槛并集（治根因 3）—— 改 `extract_claims_self_consistent`
现全并集（出现 1 次就留）→ 改频率门槛：统计每个主张在 N 次抽样中出现的次数，
**只在 ≥ MIN_FREQ 次出现的主张进最终集**（默认 MIN_FREQ = ceil(N/2) = 2/@N=3）。
一次性幻觉/随机丢失直接滤掉。保留 CE3 溯源 + MiniCheck 抓系统性错的组合。

阈值权衡（待用户拍板）：
- 方案 X：N=3, MIN_FREQ=2（省 key，较激进，可能误杀只出现 1 次但对的主张）
- 方案 Y：N=5, MIN_FREQ=2（更稳，多烧 ~2/3 key）
- 组合：N=3 + "高置信主张（factuality=factual 且 MiniCheck 通过）即使仅 1 次也留"作为豁免

---

## 三、与现有 A 的关系

| 层 | 现状 | 本方案后 |
|---|---|---|
| 输出长度 | A：分页 5/页 + 公式预算 1320 封顶 | 不变（A 已治"长输出触顶"） |
| 空响应 | 不检测 → 直接丢页 | 对策1：检测+重试（指数退避） |
| 截断 | 整页丢弃 | 对策2：续写游标（不抬高上限） |
| 漂移 | 全并集（1次就留） | 对策3：频率门槛并集（≥2/3 才留） |

A 解决"长输出触顶"，本方案解决"空响应 + 截断 + 漂移"——互补，不冲突。

---

## 四、验证计划

1. 实施对策 1/2/3 + 选定阈值方案。
2. 语法校验 + 不烧 key 的确定性/mock 单测（扩展 test_claim_stability：mock 空响应→重试成功；mock 截断→续写恢复）。
3. 鲁棒性测试（BV1h1LD6BELK）对比（**默认带缓存**，非 `--no-cache`）：
   - B（频率门槛）只在单次 refine() 调用的 n=3 抽样内去噪；**跨 3 次独立调用的稳定性靠 CE4 缓存冻结主张集**
     （v0.4.6 升级为「冻结最终主张集」→ 复查完全确定性复现，根治跨调用漂移 #141）。
   - 默认带缓存重跑：主张数三轮收敛（同一数值，不再 2/4/5）、真实性标签稳定、MiniCheck 本地真验出事实主张判定。
   - 注：`--no-cache` 下 3 次独立重抽，B 压不住跨调用方差，属预期（非 B 的 bug）。
4. 记入 CHANGELOG（新增 [0.4.5] 韧性层？或并入 0.4.3 备注——待定）。

---

## 五、待用户拍板

1. 阈值方案：X（N=3/MIN_FREQ=2）/ Y（N=5/MIN_FREQ=2）/ 组合豁免？
2. 是否并入现有版本号还是开新 [0.4.5]？
3. 确认后实施（不擅自改）。
