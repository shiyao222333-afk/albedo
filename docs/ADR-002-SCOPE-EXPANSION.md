# ADR-002: Albedo 范围扩张 —— 多维鉴定 + 多源输入 + 平台信号归一化 + 文本类型感知

## Status
Accepted（2026-07-09）

## Context
炼真立项时定为「验真假核心闭环」（单源、单标签 真/假/可疑）。用户在立项后实践中提出 4 项扩张，并补充 1 项关键区别：

1. **验真假可借统计学**：除大模型判断，还可用统计学手段（跨源共识频率、数值自洽、离群检测）补充验证。
2. **输入不止视频字幕**：还要处理微信/小红书文案，未来 PPT/Excel 文档文字。
3. **平台带来内容之外的信号**：如 B站 播放量 / 受众画像 / 点赞收藏评论，应结合分析。
4. **评价应多维度**：真实性 ≠ 文案/结构/逻辑优秀，报告需分维度呈现。
5. **用户补充**：字幕（口语转录、零碎）与结构清晰的文案，处理方式本就不同——同是"文字"但不能一视同仁。

## Decision

- **多维鉴定**：`quality` 从单 label 改为多维对象（`truthfulness` / `copywriting` / `structure` / `logic`）。`status` 由 `truthfulness` 推。v0.1.0 只实现 `truthfulness` 维度，但**数据模型从一开始多维**，避免 v0.2.0 返工。
- **验真假双方法**：大模型（nuwa 三重验证 / OpenFactCheck）+ 统计学（MVP 轻量数值自洽，规模期跨源共识）。
- **多源输入 + 文本类型感知**：Albedo 仍只吃文字（平台无关），但输入带 `text_type`（subtitle / social_post / article / doc_ppt / doc_excel）标记，净化与评估据此调整策略（字幕走 ASR 清洗 + 重结构，结构化文案直提炼）。各格式抽取归 Nigredo「一对象一适配器」。
- **平台信号归一化**：平台元数据由 Nigredo 归一化为统一信号包（`engagement` / `audience` / `sentiment`）传入 `signals` 字段；Albedo 只吃归一化信号，不碰原始平台字段，保持平台无关。

## Consequences

- **更易**：报告信息量大幅提升，真假与"好不好"分离，避免误杀好内容 / 误收漂亮谎言；未来多平台、多格式接入零改动炼真核心。
- **更难**：LLM 输出结构更复杂（多维 JSON），v0.1.0 虽只填 `truthfulness` 但需预留维度；需与 Nigredo 约定 `text_type` + `signals` 契约。
- **依赖**：Nigredo 适配器需扩展（抓元数据 + 标 `text_type` + 归一化信号），属 Nigredo 范围，本次仅定契约、不改 Nigredo 代码。

## 影响的文档
- `BLUEPRINT.md`：质量评估→多维鉴定；内容净化加文本类型说明；输入来源与平台信号段。
- `FLOWCHART.md`：C1 输入补 text_type/signals；C2 按类型净化；C3 多维评估；接口边界加文本类型感知。
- `PROJECT_PLAN.md`：借鉴地图补统计学；独特之处 #2 加文本类型感知；版本路线 v0.1.0/v0.2.0 反映多维；数据契约 quality 多维化 + text_type/signals；T1/T2/T3 任务描述更新；验收标准改多维报告。

## 竞品佐证（2026-07-09 补充）
本次扩张的 4 项决策均有成熟方法/研究可借，非拍脑袋（详见 `docs/ALBEDO-RESEARCH-2026-07-09.md` 11.6/11.7）：
- **多维鉴定**：TruthfulnessEval（多维真实性）、AIGVQA（多维质量）、Acrolinx/Writer/Grammarly + ETS e-rater（写作质量多维）——但无「真实性+质量」组合，空白即护城河。
- **统计验真**：NumTemp（数值/时间断言验证）、Cross-Document Fact Verification（跨文档验证）对应「数值自洽 / 跨源共识」。
- **平台信号**：Viblio（视频可信度信号）精确命中；但须加护栏 **Engagement Is Not Evidence**（互动信号≠真实证据），信号仅作辅助维度。
- **商业参照**：Logically / FactBox.ai / iWeaver / Winston AI / FactSnap 均为单维真实性核查器，仅作「真实性」一维参照。
