# 验真环节研究 V3 — 角度补漏（V2 的 7 个遗漏维度）

> 前两轮聚焦「验真怎么跑」（抽断言→查证据→逐条验）+「熔知怎么存」（epistemic_status / is_personal / trust_score）。
> 本轮从**侧面**补查，发现 V2 设计有 7 个明显遗漏。本文逐条给出：是什么 / 对咱们的意义 / 怎么落地（便宜 vs 重）/ 映射到现有代码或熔知字段。
> 结论：V2 的主干（两轴 + 三维度 + 逐条）方向对，但需补 3 个「零成本/不联网」的能力 + 2 个「防坑」机制 + 2 个「持久化」扩展。

---

## 遗漏 1：视频自己打自己脸（内部自相矛盾）— 不联网、零成本、高价值

**是什么**
- ContraDoc（2023）：首个文档级自相矛盾数据集。长文档里前后隔很远的两句话矛盾，人很难发现（人准确率 26.7%），GPT-4 也才 34.7%，且越长越难。
- 关键性质（ETH Zurich 2023）：**两个互相矛盾的断言不可能同时为真 → 自相矛盾=逻辑必然不实**，不需要上网查，纯逻辑可判定。

**对咱们的意义**
- 咱们有**完整字幕 + 时间戳**，这是巨大优势：把抽出的每条断言两两做 NLI（蕴含/矛盾/中立），矛盾对直接标红，且能点开看"第 3:21 说 A、第 12:08 说非 A"。
- 这是**第一层（不联网）就能做**的最强信号之一，且误报极低（逻辑确定）。

**怎么落地**
- 抽取原子断言后，对所有 `(claim_i, claim_j)` 对跑 cross-encoder `nli-deberta-v3-base`（GPU 20-30ms/对，RTX 3080 跑得动）。
- 矛盾对 → 在 ClaimVerification 上加 `contradicts_with: [claim_id, ts_a, ts_b]`，报告标「⚠️视频自相矛盾」。
- 注意：只检"显性矛盾"（数值/否定/最高级），混合类（"A 好"vs"有时 A 不好"）留给 LLM 判，避免误报。

---

## 遗漏 2：事实会过期（时效性 / recency）— 接熔知 temporal_nature

**是什么**
- factcheckr.io「Living Fact Checks」：真相有生命周期，证据会变（法规改、研究被撤、数据更新），静态判定会"老成谣言"。应带版本、可重验。
- 信源可信度三支柱（freeacademy）：**Authority（谁说）/ Corroboration（有人佐证吗）/ Recency（还新吗）**——Recency 是独立一维。
- CRAAP 测试五要素：Currency（时效性）排第一。

**对咱们的意义**
- 咱们是「一人公司」，关注的是**平台规则 / 工具价格 / 玩法**——这些变最快。2023 年验证"某功能免费"的断言，2026 年可能已收费。
- V2 设计的 ClaimVerification **完全没有时间维**：验出来"supported"没写"基于哪天的知识"，将来过期了还当真。

**怎么落地**
- ClaimVerification 加 `verified_date`（核查日）+ `validity_class`（接熔知 temporal_nature：evergreen 永恒 / timeboxed 限时 / transient 易逝）。
- 平台规则/价格类默认 timeboxed，报告标"⚠️此结论有时效，建议 [verified_date] 后复核"。
- 熔知入库时 `temporal_nature` 分面直接接这个字段；后续可做"定期重验"任务（v1.3.0 项目间通信后）。

---

## 遗漏 3：验真 AI 自己瞎编断言（抽取幻觉）— 比总结瞎编更危险的坑

**是什么**
- 抽取断言这步用 LLM，**它会无中生有**（extrinsic hallucination）：视频没说的话，它当成"原子断言"提取出来，然后还拿去"验证"、当视频的主张呈现。
- codersarts / sohu / RAGAS 共识：**唯一有效对策 = 独立的忠实度核查**（groundedness/faithfulness）——每条抽出的断言拿原文 NLI 一遍，看是否被源文本蕴含。
- 铁律：**验证模型必须与生成模型独立**（"不能让学生改自己卷子"），否则同一偏差反复出现。
- 最危险指标是 **confident-wrong**（断言了、无支撑、还没保留余地）——有研究实测 3.1% 这类。

**对咱们的意义（重要）**
- 咱们 V2 只给**总结**做了忠实度自检（`grounding.py` 标「⚠️无原文支撑」），但**抽出的断言没做同样的核查**！
- 这意味着：一条 LLM 编的"视频说转化率 30%"，会被当成视频真实主张去验、去呈现——比总结编一句更阴险，因为带"已验证"光环。

**怎么落地（关键补漏）**
- 在 claim 抽取后、验真前，插一步 **claim faithfulness guard**：每条抽取断言 vs 字幕原文跑 NLI/MiniCheck，未蕴含的直接丢弃或标 `faithfulness=ungrounded`（不让它进验真流程）。
- 验证模型用 MiniCheck（独立小模型），不与抽取用的大模型同源 → 满足"独立核查"。
- 这就是把现有 `grounding.py` 的能力**复用**到 claim 上，不是新发明。

---

## 遗漏 4：画面也会骗人（多模态 / 跨模态矛盾）— 当前管线完全盲区

**是什么**
- GroundLie360（2025，武大/新国立/北大）：首个多模态虚假定位基准，6 类（假标题、篡改时序、AI 生成图、跨模态矛盾等），2000+ 视频。
- Misleading ChartQA（2025）：21 类误导图表，多模态大模型也常翻车。
- ShortCheck（IJCNLP 2025）：短视频核查流水线 = 语音转写 + **OCR** + 物体/深伪检测 + 视频描述 + 断言验真，F1>70%。

**对咱们的意义**
- B站视频有画面。创作者可以放**假截图、PS 过的收益面板、误导图表**——咱们当前只看字幕，**完全抓不到**。
- 但有个**不联网就能抓的便宜信号**：**跨模态矛盾**——字幕说"免费"，画面文字（OCR）写"¥99"；字幕说"日入过万"，画面收益图字体不对。这类用 OCR + 字幕对齐即可，不需联网。

**怎么落地（分两档）**
- 便宜档（做）：关键帧 OCR（可用现成 PaddleOCR/tesseract）+ 与字幕断言做跨模态矛盾比对，命中标 `is_visual_claim=True, cross_modal_contradiction`。
- 重档（暂不做/标注局限）：深伪检测、图表误导识别需 VLM，RTX 3080 能跑小 VLM 但重，列为 v0.3+ 扩展；当前对所有"纯画面主张"统一标 `is_visual_claim=True, unverified`（诚实声明"画面内容未核查"）。

---

## 遗漏 5：误报的代价（标错了比漏标更伤）— 必须校准 + 保守

**是什么**
- Nature（2026）：小模型有**"自信-能力悖论"**——准确率低却照样高自信，容易误伤。
- Justice in Misinfo：误报（把真内容标假）造成**信源声誉损害**、构成"参与不公"，高误报率尤其伤小信源。
- Gravity7：AI 核查标签会**适得其反**——随机实验发现 AI 核查并没提升辨真能力；当 AI 把真标题错标假，人们反而更不信真的了。标签在"重新分配信任"，不一定是加分。

**对咱们的意义**
- 咱们是**个人决策辅助**：把一条靠谱 UP 主的真经验错标"可疑"，会让我错过好方法；比"漏掉一条谎言"代价更隐性。
- 所以**默认应是"未验证"而非"假"**，且必须给置信度，让用户自己拍板。

**怎么落地**
- ClaimVerification 加 `confidence`（校准后置信度）+ 默认 verdict=`unverified`（FAXTR 标准）。
- 只有"逻辑矛盾 / 强证据推翻 / 绝对化骗局话术命中"才升 `contradicted`/`suspect`；其余一律 `unverified`，报告写"未查到反证，不代表为真"。
- 阈值保守化（宁可放过、不要误伤），与 V2 双轴设计一致。

---

## 遗漏 6：创作者怎么规避核查（话术逃避）— 接 V2 的 fact/opinion + personal/public

**是什么**
- Weasel words（水词）："研究表明""专家说""大多数人同意"——听起来有权威，实际无出处。
- Hedge（模糊语）："可能""大概""或许"——低承诺、可赖账；CoNLL-2010 有 SOTA 检测。
- EvasionBench（2026）：财报问答回避检测，3 级回避，Eva-4B 达 81.3%。"不构成投资建议"式免责声明是典型逃避。

**对咱们的意义**
- 卖课创作者最爱用：把"个人体会"包装成"普适规律"（"这方法谁用都灵"），或用水词显得有依据却不担责。
- 这正好和 V2 的 **fact/opinion + personal/public** 联动：带水词/模糊语却以"事实+公开"陈述的 → 提升 check-worthiness；标 `hedge_level` / `weasel_flag`。

**怎么落地**
- 抽取时顺带标 `hedge_level`（0 绝对 / 1 弱保留 / 2 强模糊）+ `weasel_flag`（含"研究/专家/多数"无出处词）。
- 报告里给"这句话用了模糊/水词，建议视为个人观点而非铁律"。
- 纯规则 + 轻 LLM 即可，不联网。

---

## 遗漏 7：UP 主信用应跨视频累积（创作者级信誉聚合）— 新持久化物

**是什么**
- 链上声誉（omniscient）：每条断言+核查结果+更正都记录，累计准确率=作者声誉，激励与"准"对齐。
- Wikipedia 信任着色：作者声誉来自"贡献存活时长"——活久涨分，被回退掉分。
- Source Score：credibility 0-10 = f(verified_count, misleading_count, total_volume)，带上下文不全信。

**对咱们的意义**
- 咱们现在每视频独立评 trust_score，**UP 主信用不累积**。但"这个 UP 主 10 条视频的断言 9 条被证实"比"这一条碰巧对"可信得多。
- 应有一个**跨视频的创作者信任档案**（可落 Nigredo 的 creator_center 四块数据 / 或熔知 is_personal 聚合）。

**怎么落地**
- 新增 `creator_reputation`（持久化）：每条视频验完，把逐条 verdict 聚合进该 UP 主的滚动分（加权、带衰减）。
- 落点：Nigredo 采集时已有 creator 维度；炼真输出 `creator_id` + 本视频贡献的 ±分；由 OpusMagnum 或熔知聚合。
- 本期先定义字段 + 单视频内聚合，跨视频累积留待 v0.3（接项目间通信）。

---

## 修订后的 ClaimVerification 记录（V2 + V3 补漏）

```python
ClaimVerification = {
  # —— V2 原有 ——
  quote, ts,                      # 原话 + 字幕时间点
  factuality: factual/opinion/mixed,   # 维度2 事实观点
  scope: personal/public,              # 维度3 个人公开
  check_worthy: bool,                  # 经验主张放过
  accuracy: supported/contradicted/unverified,  # 维度1 准确性轴
  evidence_grade: L1..L4,
  epistemic_status,                    # 落熔知
  trust_score,                         # 落熔知
  evidence + human_explanation,

  # —— V3 补漏新增 ——
  faithfulness: grounded/ungrounded,   # 遗漏3: 这条断言真从字幕抽的?（防 LLM 瞎编）
  contradicts_with: [claim_id, ts_a, ts_b] | None,  # 遗漏1: 自相矛盾对
  verified_date, validity_class,       # 遗漏2: 时效（接 temporal_nature）
  is_visual_claim: bool,               # 遗漏4: 画面主张（当前 unverified）
  cross_modal_contradiction: bool,     # 遗漏4: 字幕 vs 画面文字矛盾
  hedge_level, weasel_flag,            # 遗漏6: 话术逃避
  confidence,                          # 遗漏5: 校准置信度（默认 unverified）
  creator_id, creator_rep_delta,       # 遗漏7: 跨视频信用累积
}
```

## 修订后的流水线（Layer 0.5 是新增防坑层）

```
Layer 0.5 (新增防坑, 不联网):
  抽断言 → claim faithfulness guard (MiniCheck/NLI vs 字幕) → 丢 ungrounded
        ↓
Layer 1 (不联网快筛):
  - 话术识别: 绝对化骗局话术 / weasel / hedge  → suspect
  - 自相矛盾: 两两 NLI → contradicts_with 标红
  - 时效标记: validity_class + verified_date
  - 跨模态: OCR vs 字幕 → cross_modal_contradiction（关键帧）
  - 事实/观点 + 个人/公开 分类（V2）
        ↓
Layer 2 (联网深验, 仅 check_worthy 事实+公开):
  - 抽证据 → MiniCheck 逐条验 → supported/contradicted
  - 聚合 → 文档级 epistemic_status / trust_score / is_personal
  - 跨视频 → creator_reputation 累积（v0.3）
```

## 与现有代码的映射

| 补漏 | 复用/新增 |
|------|-----------|
| 遗漏3 claim faithfulness | 复用 `core/grounding.py` 的 NLI 能力，从"验总结"扩到"验断言" |
| 遗漏1 自相矛盾 | 新增 `core/self_contradiction.py`（pairwise NLI） |
| 遗漏2 时效 | 落 `RefinedKnowledgeObject` + 熔知 `temporal_nature` 分面 |
| 遗漏4 跨模态 | 新增 `core/cross_modal.py`（OCR 依赖，关键帧） |
| 遗漏5 校准 | `assess.py` 默认 unverified + confidence 字段 |
| 遗漏6 话术 | 并入 `classify.py` 的抽取 prompt（hedge/weasel 标柱） |
| 遗漏7 信用 | 新增 `creator_reputation` 聚合（v0.3，接项目间通信） |

## 结论

V2 主干没错，但**漏了"验真本身也会被污染"这道防线**（遗漏3 最危险），以及三个"不联网零成本"却能抓大量骗局的能力（自相矛盾 / 时效 / 跨模态）。加上"误报代价"的保守校准和"UP 主信用累积"，验真才完整。

**建议实现顺序（同内容线节奏）**：先做 Layer 0.5（防瞎编）+ Layer 1 四能力（不联网），Layer 2 联网深验等你显卡环境 + 你确认后再上；遗漏7 跨视频累积排最后。

## 仍待用户拍板

1. Layer 0.5（claim 忠实度核查）现在就加？——**强烈建议加，否则验真结果可能被 LLM 编的断言污染**。
2. 跨模态 OCR 这轮做还是标注局限（所有画面主张标 unverified）？—— 我建议先标局限，关键帧 OCR 排 v0.3。
3. UP 主跨视频信用累积，本期只定义字段、不做聚合？
