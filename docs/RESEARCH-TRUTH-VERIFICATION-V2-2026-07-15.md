# 验真环节深化研究 V2（结合熔知字段 + 真假/事实观点/个人公开三维度）

> V1（RESEARCH-TRUTH-VERIFICATION-2026-07-15.md）只研究了"怎么验"（抽 claim→查证据→逐条验），**没接熔知存储字段**。
> 用户指出缺口：验真结果必须落到熔知的 `epistemic_status` / `is_personal` / `knowledge_type` / `trust_score`。
> 本篇补三维度：**真假（准确性轴）**、**事实观点（验真前提筛选）**、**个人公开（验真范围）**，并设计"逐条验真记录 → 文档级 → 熔知字段"的完整映射。
> 结论先行：验真应产出一个**逐条 ClaimVerification 记录**（含三维度），再聚合映射进熔知分面。真假与 epistemic_status 是**正交两轴**（准确性 vs 证据强度），不能混为一谈。

---

## 1. 熔知真实字段盘点（来自 config/classifications.py + field_cfg.py）

| 字段 | 值 | 含义 | 与验真的关系 |
|---|---|---|---|
| `epistemic_status` | unverified(L0猜想) / substantiated(L1逻辑验证) / corroborated(L2实证验证) | 认知验证状态，基于 FPF（arxiv 2601.21116） | **证据强度轴**（不是真假轴！） |
| `is_personal` | True(👤个人) / False(🌐公开) | 是否个人经验 | **个人公开维度** |
| `knowledge_type` | principle/formula/case/standard/concept/method/data/reference/procedure/requirement/test_data | 知识子类型 | 可由 content_extract 类型推导 |
| `trust_score` | 0-5（0未评级/5权威/4可信/3一般/2待验证/1存疑） | 可信度 | **准确性轴的主要落点** |
| `content_type` | 15 类 | 内容类型 | 已由 classify 填 |

- 炼真 `IngestionMeta` 已预留 `epistemic_status` / `trust_score` / `is_personal` / `knowledge_type` 字段（adrm-005 直存熔知）。
- **当前缺口**：这些字段现在从 `Truthfulness.label(true/false/suspect)` 整体推，没细到 claim 级，也没有 fact/opinion、personal/public 维度。

---

## 2. 三个核心维度（用户点名）

### 2.1 真假（准确性轴）—— 与 epistemic_status 正交

**关键认知（最重要）**：「真假（准不准确）」和「epistemic_status（证据强不强）」是**两件事**：

- 证据强 ≠ 真：共识可能错（"疫苗致自闭症"曾被多篇论文"佐证"但实为假）。
- 没验证 ≠ 假：只是还没查（FAXTR 对查不到的标 UNVERIFIED，不猜真假）。

所以必须拆成**两轴**：

| 轴 | 名称 | 取值 | 来源 |
|---|---|---|---|
| **Axis A 准确性** | verdict | supported / contradicted / unverified | 验真产出 |
| **Axis B 证据强度** | epistemic_status | unverified / substantiated / corroborated | 熔知分面 |

**映射逻辑**（per-claim → 熔知）：
- fact + public + 外部权威证据支撑(L3/L4) → epistemic_status=**corroborated**, trust=4-5
- fact + public + 逻辑自洽但无外部查 → epistemic_status=**substantiated**, trust=3
- fact + public + 被证据反驳 → 已查实为假 → epistemic_status=**substantiated**(已查) + trust=**1**(存疑) + relations:contradicts 标红
- 无查据(unverified) → epistemic_status=**unverified**, trust=2

**参考**：FAXTR 标准化 FALSE/TRUE/HALF-TRUE/DISPUTED/UNVERIFIED；ClaimVer 逐条 contradictory(红)/extrapolatory(琥珀) + 证据溯源。

### 2.2 事实观点（fact/opinion）—— 验真的前提筛选

- **事实** = 可证伪断言（含名字/日期/数据/可查）→ 走验真。
- **观点** = 主观价值判断（评价形容词"优秀/灾难"、hedging"我认为"、比较价值判断）→ **不验真假**，改评"支撑度/自洽/信息量"。
- 给观点判 true/false 是**范畴错误**（omniscient.news：那不是新闻是鼓吹）。
- transformer 模型在 fact/opinion 基准上 85-92% 准确；**混合声称最难**（事实+观点框架，如"失业涨2点证明政府失败"——前半可查、后半是观点）。
- **三分类建议**：`factual` / `opinion` / `mixed`。

**参考**：Omniscient 三档 "Factual and Verified" / "Factual but Disputed" / "Primarily Opinion/Unverifiable"——防止把复杂混合声称误标 true/false。CheckThat! 2025 主观性检测（SUBJ/OBJ）已是成熟预处理步骤。

### 2.3 个人公开（personal/public）—— 决定验真范围

- **个人** = 第一人称经验（"我试了…多接3单"）→ 不可外部证伪，判内部自洽 + 证据等级 L1（作者声称）。
- **公开** = 可外部验证断言（"平台规则改了"）→ 走联网深验（第二层）。
- 注意：个人叙述也可能自欺/误述（TUNA 不可靠叙述者数据集，ACL 2025）——个人经验≠一定真，但错法不同于"公开事实错"，应单独标注 `is_personal=True` 而非判 false。
- **映射**：`is_personal` 字段。

---

## 3. 逐条验真记录设计（ClaimVerification）

每条原子断言产出一个结构化记录（复用 content_track 的 `key_sentences` 带 ts）：

```python
@dataclass
class ClaimVerification:
    claim: str            # 原子断言文本
    source_ts: str        # 字幕时间戳（复用 key_sentences，可点开看原句）
    fact_opinion: str     # factual / opinion / mixed   ← 维度2
    personal_public: str  # personal / public           ← 维度3
    checkworthy: bool     # 是否值得联网验（经验主张=False，放过）
    verdict: str          # supported / contradicted / unverified   ← 维度1(准确性)
    evidence_grade: str   # L1-L4（沿用 assess.py）
    epistemic_status: str # unverified / substantiated / corroborated  ← 熔知分面
    trust_score: int      # 0-5  ← 熔知分面
    evidence: list        # [{type:support/refute, text, source}]
    reasoning: str        # 人话解释（标可疑必须能点开看原因）
```

---

## 4. 逐条 → 文档级 → 熔知字段 映射

| 熔知字段 | 聚合规则 |
|---|---|
| `epistemic_status` | 逐条加权主导：有 corroborated 则整体偏 corroborated；全 unverified 则 unverified |
| `is_personal` | 任一 claim 为 personal → True（或个人claim占多数） |
| `trust_score` | 逐条 trust 聚合（假 claim 拉低整体；取加权平均或最小值钳制） |
| `knowledge_type` | 从 content_extract 类型推导（sop→method, decision→case, concept→concept…） |
| `relations` | 矛盾 claim → `contradicts` 关系 + 报告标红 |
| `content_type` | 已由 classify 填（tutorial/tool_review…） |

---

## 5. 两层方案 + 三维度融合（更新 V1）

### 第一层（不联网，必做）
对每条 claim 打：personal/public + fact/opinion + 初步 verdict（规则+话术红色信号+逻辑自洽+数值自洽）。
- 数值自洽（已有）+ 补"伪权威/绝对化疗效"规则
- fact/opinion 分类（LLM 或规则）
- personal/public 分类（LLM 或第一人称线索）
- 经验主张(personal+opinion) → checkworthy=False，放过，标 is_personal

### 第二层（联网深验，已确认做）
- claim 抽取：复用 `key_sentences` → 拆原子断言 → 过滤 checkworthy（只验 fact+public）
- 检索证据：未来接搜索 API；MVP 先本地知识库比对（熔知 Qdrant 跨源共识）
- 逐条验：MiniCheck 本地 GPU（supported/contradicted）→ 映射 epistemic_status + trust_score
- **双信号增强**（来自 TruthLayer）：语义相似度 × 实体矛盾惩罚（数值/否定/最高级 vs 具体），专治"2% vs 4%罚款"类数值陷阱

### 决策点（用户已确认）
1. ✅ 第一层+第二层都做
2. ✅ 经验主张放过（只验 fact+public 的可证伪事实）
3. ✅ MiniCheck 本地部署（RTX 3080）
4. ✅ 逐条粒度（ClaimVerification 记录）

---

## 6. 轻量实现要点（来自竞品拆解）

- **TruthLayer**：双信号（embedding × 实体矛盾惩罚）验证数值类声明——验证咱"数值自洽"方向对，且解释为何数值 claim 需特殊处理。
- **ASET**：YouTube→原子 claim(LLaMA 3.3 70B)→逐条验→stance(supports/contradicts/neutral)+trust——我们的目标形态（抽claim→逐条验→trust）。
- **ClaimVer**：逐条 contradictory(red)/extrapolatory(amber)+KG证据溯源——报告渲染参考（标红/标琥珀）。
- **MiniCheck**：本地 GPU 跑验证(supported/contradicted)，便宜 GPT-4 的 400 倍。

---

## 7. 参考文献（V2 新增）

1. ClaimVer: Explainable Claim-Level Verification and Evidence Attribution through KGs. arXiv:2403.09724
2. FAXTR Methodology. https://faxtr.com/methodology （FALSE/TRUE/HALF/DISPUTED/UNVERIFIED 标准化）
3. TruthLayer (AWS). https://dev.to/coldstartdev/truthlayer-how-i-built-an-ai-hallucination-firewall-on-aws （双信号验证）
4. ASET (AWS AIdeas). https://builder.aws.com/.../aideas-finalist-aset （YouTube→原子claim→逐条验→trust）
5. Opinion vs Fact in Journalism. https://omniscient.news/blog/opinion-vs-fact-journalism （事实/观点范畴错误）
6. XplaiNLP at CheckThat! 2025: Multilingual Subjectivity Detection. arXiv:2509.12130 （SUBJ/OBJ 成熟任务）
7. Classifying Unreliable Narrators with LLMs (TUNA). ACL 2025. https://aclanthology.org/2025.acl-long.1013.pdf （个人叙述可靠性）
8. Claim Verification in the Age of LLMs: A Survey. arXiv:2408.14317 （claim detection→retrieval→veracity 三组件）
9. 熔知字段定义：D:\citrinitas\config\classifications.py / field_cfg.py
10. 炼真数据契约：D:\albedo\core\models.py（Truthfulness / IngestionMeta）
