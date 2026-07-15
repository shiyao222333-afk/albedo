# 验真环节调研报告（2026-07-15）

> 配套内容线 v0.2.1 完成后的下一环。目标：研究"怎么科学地验真（真/假/可疑）"，给出落地到炼真流水线的方案雏形。
> 结论先行（大白话）：现有 assess.py 是"假验真"——只识别话术特征，没真去查证事实。真正验真应拆"抽断言→查证据→逐条验"三步；业界有标准范式（OpenFactCheck）和本地能跑的轻量验证模型（MiniCheck，RTX 3080 可跑、便宜 GPT-4 的 400 倍）。验真分两层：单源快筛（必做，不联网）+ 联网深验（可选）。

---

## 0. 背景与目标

- 内容线（Track A）已完工并提交（Albedo `e82cc17`，v0.2.1）：分类 / 关键句锚定 / 高光窗口 / 按类型萃取 / 保真自检（总结是否编造）。
- 现有验真：`core/assess.py` v0.2.1，已实现 nuwa 三重验证 + L1-L4 证据分级 + 数值自洽 + 变现护栏。
- **本报告目标**：调研"验真（真/假/可疑）深化"的科学方法，明确现有 assess.py 的边界，给出落地方案雏形。**不写代码、不定计划**，待用户拍板后实现。

---

## 1. 现状盘点：已有 vs 缺口

### 1.1 已有（assess.py v0.2.1）

| 能力 | 实现 | 说明 |
|---|---|---|
| 三重验证 | `assess_truthfulness()` | nuwa 框架：来源可核验 / 逻辑自洽 / 证据强度 + L1-L4 证据分级 |
| 数值自洽 | `check_numeric_consistency()` | 规则抽收入/时间/百分比/粉丝断言；红色信号：零基础月入X万、保证赚、稳赚、永动机 |
| 变现检测 | `assess_monetization()` | 卖课话术特征 + 护栏「变现≠差内容」 |
| 输出 | `Truthfulness` | label(true/false/suspect) + score(0-100) + reasoning + evidence_grade |

### 1.2 核心缺口（关键）

- **无检索的单源判断**：整个验真是 LLM 凭 prompt 框架"凭感觉"，没去外部查证据。
  - 类比：警察看嫌疑人神色不对就怀疑，但没去查档案对不对。
  - 只能抓"话术特征明显"的假（骗局套话），抓不了"看起来专业但事实错"的假（如引用了过时/错误的平台规则、虚构的数据指标）。
- **无 claim 级粒度**：输出一条总评（true/false/suspect），不能告诉用户"第 X 条断言是假的 / 无依据"。蓝图验收标准第 4 条要求"对卖课虚假能标可疑/虚假"，但当前是整体标，无法定位到具体谎言。
- **grounding.py 只做"总结是否编造"**：那是内容线的保真质检（summary 是否被字幕支撑），与"视频说真话"是两件事，不能替代验真。

---

## 2. 业界标准范式：OpenFactCheck 三步 pipeline（EMNLP 2024, MBZUAI）

来源：http://openfactcheck.com ｜ arXiv:2408.11832

- 统一框架，把各种事实核查系统归并为**三步走 pipeline**，三个可插拔组件：
  1. **claim_processor（抽断言）**：把输入文档拆成"原子化、去语境化"的 claims——每个独立、可验证的断言。
  2. **retriever（查证据）**：为每个 claim 检索相关证据（BM25 / Wikipedia / SerpAPI 等）。
  3. **verifier（验证）**：基于证据用 NLI 判断 veracity（蕴含 / 矛盾 / 中立）。
- 可组合：FactCheckGPT 的抽取器 + RARR 的检索器 + FacTool 的验证器自由拼；YAML 配置驱动。
- **对咱们的启示**：验真应拆成三步独立模块，而不是一股脑丢给 LLM 判 true/false。这样每步可独立替换/优化/降级。

---

## 3. Claim 抽取（关键第一步）

来源：CheckThat! 2025（UNH）｜ SciClaims 2025（EMNLP Demo）｜ Fact in Fragments 2025

- **方法成熟度**：零样本 LLM 提示已能达到不错效果；微调 8B 模型提升有限；少样本 + CoT 最好（Grok3+少样本CoT 验证集 METEOR 0.332）。
- **标准流程**（CheckThat! 2025 系统 prompt）：
  1. 句子分割 + 上下文（前后各两句）
  2. 选择：是否含可核查信息？不可核查则重写只留可核查部分，或丢弃
  3. 消歧：解决指代/结构歧义，无法解决则丢弃
  4. 分解（decomposition）：复杂句拆成多个原子命题（如"他是教授且是CEO"→"他是教授"+"他是CEO"）
  5. 去语境化（decontextualized）：确保脱离上下文也能独立理解
- **SciClaims 2025**：单个 LLM 端到端（抽取+检索+验证），不微调，单 GPU 可跑。
- **复用点（重要）**：content_track 的 `key_sentences`（关键原话带 ts）已是"逐条关键句"，可直接作为 claim 候选来源，再拆成原子断言即可，不用从零抽。溯源 ts 也天然带上了。

---

## 4. 轻量验证模型（不用每次烧大模型）—— MiniCheck

来源：MiniCheck (EMNLP 2024, arXiv:2404.10774) ｜ HuggingFace lytang/MiniCheck-* ｜ GitHub jantrienes/MiniCheck

- **模型变体**：DeBERTa-v3-Large / Flan-T5-Large(770M) / Bespoke-MiniCheck-7B
- **接口**：`MiniCheck(document, claim) -> {0, 1}`（claim 是否被 document 蕴含支持）
- **性能**：Flan-T5-Large 达到 GPT-4 级（LLM-AggreFact 基准 74.7% vs GPT-4 75.3%），但**便宜约 400 倍**（评估同基准 $0.24 vs $107）。
- **本地部署**：DeBERTa-v3-Large / 7B 版均可在**本地 GPU（咱有 RTX 3080）**直接跑，无需联网调用 API。
- **对咱们的战略意义**：完美契合蓝图准则"非必要不用大模型"。验真流水线里：
  - 抽 claim（需要理解/分解）→ 用 LLM（DeepSeek）
  - **逐条验证（NLI 蕴含判断）→ 用 MiniCheck 小模型（本地、便宜、确定性）**
- 对比：SummaC / AlignScore 也是 entailment 类，但 MiniCheck（2024）更新、效果更好、有 7B 商用可用版。

---

## 5. Check-worthiness（哪些 claim 值得验）

来源：ClaimBuster (KDD 2017) ｜ ClaimRank (NAACL 2018) ｜ WorthIt (CLiC-it 2025)

- **核心思想**：不是所有句子都值得查。给每句打"可核查性 + 公共重要性"分，优先验 top-ranked。
- **定义**（Nakov et al.）：check-worthy = 事实性 + 可验证 + 可能假/有害/公众关注。
- **对咱们的过滤原则**：
  - **经验类主张**（"这方法帮我多接了 3 单""我靠这个提效 2 倍"）→ 无外部标准答案，**不值得联网查**，靠数值自洽 + 证据分级（L1 作者声称）处理。
  - **可证伪事实**（"XX 软件免费""XX 平台规则改了""行业平均转化率 30%"）→ 值得查，接检索 + MiniCheck。
  - **绝对化/骗局话术**（"零基础月入十万""包教包会必成功"）→ 规则红色信号直接抓，不必走检索。

---

## 6. 中文卖课伪科普场景的实战信号（来自辟谣平台调研）

来源：上海辟谣平台(搜狐) ｜ 北京举报中心 ｜ 凤凰网 ｜ 腾讯新闻 ｜ 丁香医生类

短视频伪科普/卖课的常见套路（可直接转化为识别规则或 LLM 提示）：

| 套路 | 具体表现 | 咱们现有覆盖 |
|---|---|---|
| 装权威 | 白大褂/假头衔/MCN 包装"演员"/无资质自称医师 | ❌ 需补（伪权威识别） |
| 吓（贩卖焦虑） | 健康/身材/育儿焦虑切入 | ⚠️ 部分（变现检测） |
| 引（妙招带货） | 先给"妙招"再推产品 | ⚠️ 变现检测覆盖 |
| 绝对化话术 | "根治""包治""100%有效""祖传秘方""独家疗法" | ❌ 需补（绝对化疗效） |
| 无资质/无批号 | 无医师证行医、消字号冒充药品 | ❌ 需补 |

- 数值自洽 + 现有红色信号已覆盖"零基础月入X万/保证赚/永动机"等收益类骗局。
- **缺口**：伪权威、绝对化疗效、无资质——需补规则或 LLM 提示识别。

---

## 7. 不联网的单源验证边界（单机现实约束）

- **现实**：咱单人单机，主要内容是 B站经验/教程类，大量是"经验性主张"，**没有外部标准答案**，联网也查不到。
- 这类只能靠（第一层，不联网）：
  1. 内部数值自洽（已有）
  2. 逻辑自洽（伪科学/骗局特征，已有部分）
  3. 常识/伪科学话术识别（需补：伪权威、绝对化疗效）
  4. 证据分级 L1-L4（作者声称 vs 多源一致）
- **真正值得联网验的**是"可证伪的具体事实"（软件免费/平台规则/数据指标），占比小，且涉及搜索 API 成本/隐私/稳定性。
- VeriFact-CoT (2025, arXiv:2509.05741)：LLM 自我验证 + 引用生成，纯 prompt 不微调，但需检索增强——可作为第二层思路参考。

---

## 8. 落地到流水线：两层方案雏形

### 第一层：单源快速筛（无需联网，必做）
- 复用 + 增强现有 `assess.py`：
  - 数值自洽（已有）
  - 补规则：伪权威识别（头衔/白大褂/资质话术）、绝对化疗效话术（根治/包治/100%有效）
  - L1-L4 证据分级（已有）
- 明显假/夸大 → 直接标 false/suspect，附"因为第 X 条证据不足/话术特征 Y"
- 成本：规则（零）+ 一次 LLM 判

### 第二层：联网深验（可选，按需）
- claim 抽取：复用 `key_sentences` → 拆原子断言 → 过滤 check-worthy（只验可证伪事实）
- 检索证据：未来接搜索 API；MVP 可先只做**本地知识库比对**（熔知已有 Qdrant，跨源共识可在此做）
- 逐条验证：MiniCheck（本地 GPU 小模型，便宜确定）
- 成本：抽 claim 用 LLM + 检索 + MiniCheck 推理

---

## 9. 待用户拍板的决策点

1. **第二层联网验证现在做？还是先只做第一层增强？**（单机/成本/隐私现实，建议先第一层）
2. **check-worthiness 过滤**：只验"可证伪事实"，经验类主张放过？（建议是）
3. **MiniCheck 本地部署（RTX 3080 跑 7B）vs 继续用 LLM 判？**（建议 MiniCheck 做验证、LLM 只做抽 claim）
4. **报告粒度**：总评 true/false/suspect，还是细化到"逐条 claim 验证结果 + 哪条支撑/矛盾/无依据"？（蓝图要求"标可疑必须能点开看原因"，建议逐条）

---

## 10. 参考文献 / 检索来源

1. OpenFactCheck: A Unified Framework for Factuality Evaluation of LLMs. EMNLP 2024. http://openfactcheck.com ｜ arXiv:2408.11832
2. MiniCheck: Efficient Fact-Checking of LLMs on Grounding Documents. EMNLP 2024. arXiv:2404.10774 ｜ GitHub jantrienes/MiniCheck ｜ HF lytang/MiniCheck-*
3. UNH at CheckThat! 2025: Fine-tuning Vs Prompting in Claim Extraction. https://www.themoonlight.io/review/unh-at-checkthat-2025-fine-tuning-vs-prompting-in-claim-extraction
4. SciClaims: An End-to-End Generative System for Biomedical Claim Analysis. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.11/
5. Fact in Fragments: Deconstructing Complex Claims via LLM-based Atomic Fact Extraction and Verification. https://www.themoonlight.io/zh/review/fact-in-fragments-deconstructing-complex-claims-via-llm-based-atomic-fact-extraction-and-verification
6. ClaimBuster: Detecting Check-worthy Factual Claims. KDD 2017. https://ranger.uta.edu/~cli/pubs/2017/claimbuster-kdd17-hassan.pdf
7. ClaimRank: Detecting Check-Worthy Claims in Arabic and English. NAACL 2018. https://aclanthology.cn/N18-5006
8. WorthIt: Check-worthiness Estimation of Italian Social Media Posts. CLiC-it 2025. https://clic2025.unica.it/wp-content/uploads/2025/09/34_main_long.pdf
9. VeriFact-CoT: Enhancing Factual Accuracy and Citation Generation in LLMs via Multi-Stage Self-Verification. arXiv:2509.05741
10. 中文伪科普/卖课套路调研：上海辟谣平台(搜狐)、北京举报中心、凤凰网、腾讯新闻多篇（2025-2026）
