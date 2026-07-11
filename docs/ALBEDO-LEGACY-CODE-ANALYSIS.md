# 旧 `albedo` 仓库代码分析（2026-07-11）

> 备份位置：`D:\albedo-old`（完整含 git 历史）
> 处理背景：GitHub 上已存在同名 `albedo` 仓库，内容是与本地 v0.2.0 不同的旧版。已备份到本地，强制推送本地 v0.2.0 覆盖远程。本分析基于 `D:\albedo-old` 的实际代码。

---

## 一、旧代码到底是什么

不是一个空壳，是**认真写过的"跨源矛盾检测引擎"**——把多个信息来源的说法互相比较，找出互相矛盾的地方。

完整流水线（README + 代码印证）：

```
文档 → 声明提取(LLM) → NLI矛盾检测(transformers模型) → D-S证据融合(numpy) → TMS真值维护(纯Python) → 报告(Jinja2)
```

界面是 Streamlit 四页签：① 声明提取 ② 矛盾检测 ③ 可信度分析 ④ 报告查看。

### 各模块核查结果（都是真代码，不是占位）

| 模块 | 功能 | 技术 | 能否直接跑 |
|------|------|------|:----------:|
| `claim_extractor.py` | 用大模型从文本提取结构化"声明"（谁说啥、啥条件） | httpx 调 LLM | ✅ 立即可用 |
| `nli_detector.py` | 用 NLI 模型两两比对声明是否矛盾 | torch + transformers（mDeBERTa-XNLI） | ⚠️ 需装重型ML+下模型 |
| `ds_fusion.py` | Dempster-Shafer 证据融合（信念/似真度/冲突/裁决） | 纯 numpy | ✅ 立即可用，写得规范 |
| `tms.py` | JTMS 真值维护（信念网络、传播、矛盾、衰减） | 纯 Python | ✅ 立即可用，完整 |
| `report_generator.py` | 生成 HTML/MD/JSON 报告 | Jinja2 | ✅ 立即可用（17KB） |
| `source_reliability.py` | 来源可信度评分 | 纯 Python | ✅ |
| `graph_builder.py` | 矛盾依赖图 | networkx | ✅ |
| `athanor_bridge.py` | 同步结果回 Citrinitas 知识库 | REST | ✅ |

配置用 `KB_LLM_*` 环境变量（和我们现在本地 v0.2.0 **完全一样**），说明它是同一套"五器"体系里更早的一版设计。NLI 模型是 HuggingFace 上真实的 `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`。

---

## 二、能不能用？

**结论：能用，而且有价值——但它做的是和我们现在不同的事。**

### 直接可复用的部分（纯 Python，轻依赖）
`ds_fusion.py`、`tms.py`、`claim_extractor.py`、`report_generator.py`、`source_reliability.py`、`graph_builder.py` —— 这些不依赖重型 ML，装几个轻包就能跑，代码质量高、数学正确。

### 唯一门槛
`nli_detector.py` 需要 `torch + transformers + sentence-transformers` + 下载 XNLI 模型（几 GB）。你机器是 RTX 3080 + CUDA 12.6，能跑，就是要花时间装。

### 和我们本地 v0.2.0 的根本区别
- **我们本地 v0.2.0** = **单条内容可信度鉴定**（这条 B站/公众号内容本身真不真、能不能信，入库前质检）——这是 MVP
- **旧代码** = **跨源矛盾检测**（多个 UP 主/来源的说法互相矛盾，谁在瞎说）——这是更后面的"规模期"功能

你的蓝图里**明确写着"跨源矛盾检测 = 规模期才做"**。而旧代码恰好就是把这个规模期功能提前做出来了。

---

## 三、建议

1. **现在不用动它**：当前 MVP 重点是把单条内容鉴定做扎实，旧代码的重型 ML（NLI）和跨源定位暂时用不上。
2. **但它是未来的宝库**：等做到"规模期跨源矛盾检测 / 信任聚合"时，`ds_fusion.py`（证据融合引擎）和 `tms.py`（信念网络）这两个纯 Python 模块，正是那时需要的底层引擎——可以直接移植进来，省得从零写。这正是蓝图里"信任聚合（FPF）"和"跨源矛盾检测"的物理落点。
3. **备份留着**：`D:\albedo-old` 随时可翻，不急着重用。

---

## 四、本次 Git 操作记录

- 备份：`git clone` 旧 `shiyao222333-afk/albedo` → `D:\albedo-old`（含完整历史）
- 安全核查：确认 `.env` 已被 `.gitignore` 忽略，密钥不会泄露
- 推送：本地 `master` 改名 `main` → `git remote add origin` → `git push --force -u origin main`
- 结果：远程 `main` 从 `70950e3`（旧脚手架）强制更新到 `95ab329`（v0.2.0），推送成功
- 注：GitHub MCP 无"删除整个仓库"工具，故用强制推送等价实现"删旧+上传新"；本地已留底，无数据丢失
