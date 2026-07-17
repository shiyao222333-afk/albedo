"""Albedo (Lian Zhen) · 验真环节流水线 (v0.3.0)

验真 = 把视频里的"断言"一条条揪出来，分别判断真假/可疑，而非只给整条视频一个总分。
对应研究 docs/RESEARCH-TRUTH-VERIFICATION-V2 / -V3。

分层（用户拍板）：
  Layer 0.5 (防坑, 不联网): 抽断言后做忠实度核查 —— 每条抽取断言拿字幕原文 NLI 一遍，
               LLM 瞎编的(视频没说的话)直接丢弃，否则它会披着"已核查"外衣骗人（V3 遗漏3，最危险）。
  Layer 1 (不联网快筛): 话术识别(绝对化骗局/水词/模糊语) + 自相矛盾(两两 NLI) +
               时效标记(verified_date + validity_class) + 事实观点/个人公开分类（V2 三维度）。
  Layer 2 (联网深验, MiniCheck 本地): 抽证据→MiniCheck 逐条验 supported/contradicted。
               沙箱/未部署 MiniCheck → 全部标 unverified（保守，V3 遗漏5），接口留好待本机启用。

OCR 跨模态、UP 主跨视频信用累积：按用户指示列入路线图，本期仅定义字段、不实现逻辑。

设计铁律（沿用内容线）：
  - 确定性：call_llm_json temperature=0 + 固定 JSON schema 枚举
  - 全程 try/except 包裹每步，失败→安全默认续跑，绝不整条中断
  - 抽取断言锚定 key_sentences（真实字幕原话），从源头降低瞎编风险
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from datetime import date
from typing import Optional

from core.llm import call_llm_json
from core.form_track import apply_rhetoric_rules, _norm_cn  # 修辞规则库单一来源（v0.4.0 迁至形式线）
from core.salience import build_skeleton                       # CE0 形式信号骨架（确定性）
from core.claim_cache import load_claim_cache, save_claim_cache, compute_verify_sig  # CE4 主张缓存
from core.web_verify import web_verify_claims                  # Layer3 联网核查框架

logger = logging.getLogger("albedo.truth_track")

# ── v0.4.2 预设参数（设计文档 §4.3，先给值，#2 评测集后调）──
TOP_K_SKELETON = 12   # 骨架候选句数
N_SAMPLES = 3         # 自一致性抽样次数
RESPONSE_FORMAT = {"type": "json_object"}  # 约束解码（DeepSeek 结构化输出；该模型不支持 json_schema 严格模式）

# A. 分页 + 公式预算（治截断，科学封顶，绝无限加 max_tokens）
CLAIM_PAGE = 5            # 每页最多抽取的主张数
TOKENS_PER_CLAIM = 220    # 单条主张 JSON 估算 token 上界
PAGE_SAFETY = 1.2         # 安全系数
PAGE_BUDGET = int(CLAIM_PAGE * TOKENS_PER_CLAIM * PAGE_SAFETY)  # ≈1320，按页公式预算，确定封顶
PAGE_RETRY = 1            # 单页截断时同预算重试次数（不抬高上限，仅一次兜底）

# Layer2 未部署说明（沙箱标 unverified 时记录的口径）
LAYER2_NOTE = "Layer2 联网深验(MiniCheck 本地)未部署，本轮标 unverified；本机部署后启用逐条验真。"


# ───────────────────────────────────────────────────────────────────────────
# 规则库：时效（Layer1c）；修辞规则已迁至 core.form_track（单一来源，truth_track 消费）
# ───────────────────────────────────────────────────────────────────────────
# 时效关键词（命中→timeboxed 限时）
_TIMEBOXED_KW = re.compile(
    r"(规则|规定|政策|法规|平台|算法|机制|制度|条款|公约)"
    r"|(价格|费用|收费|票价|费率|佣金|定价|售价|报价|定金|首付)"
    r"|(版本|更新|改版|升级|新版|v\d|改版|迭代)"
    r"|(门槛|限额|限制|上限|下限|配额|封顶|底线)"
    r"|(20\d\d年|今年|现在|目前|最新|当前|截至)"
)


def _ts_to_sec(ts: str) -> float:
    """'03:21' → 201.0；解析失败返回 0.0。"""
    if not ts:
        return 0.0
    m = re.match(r"(\d{1,2}):(\d{2})", ts)
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + int(m.group(2))


# ───────────────────────────────────────────────────────────────────────────
# Layer 0: 抽取原子断言（锚定 key_sentences 真实原话）
# ───────────────────────────────────────────────────────────────────────────
_CLAIM_SYSTEM = """你是验真断言抽取器，隶属于「炼真(Albedo)」流水线。
任务：从给定「关键原话」中抽取原子断言（每条独立、可验证的小主张）。

规则：
1. 每条断言必须锚定到一条「关键原话」——quote 取原话原文（可微调措辞，但不得添加原话里没有的事实）。
2. 若一条原话含多个独立主张，拆成多条断言。
3. 判断每条：
   - factuality: factual(可证伪事实) / opinion(主观价值判断) / mixed(前半事实后半观点)
   - scope: personal(第一人称经验"我试了…") / public(可外部验证的公开断言)
   - check_worthy: 是否"可证伪的事实主张"（personal/opinion 多为 False，public+factual 为 True）
   - hedge_level: 0(绝对,无保留) / 1(弱保留,如"比较""往往") / 2(强模糊,如"可能""大概""据说")
   - weasel_flag: 是否含水词（"研究表明""专家说""大多数人同意"等无具体出处的权威暗示）

输出保持紧凑：quote 为原话片段（≤40 字），其余字段为短枚举标签。
只输出 JSON（不要解释）：
{
  "claims": [
    {"claim_id":"c0","quote":"<原话>","ts":"mm:ss","factuality":"factual|opinion|mixed",
     "scope":"personal|public","check_worthy":true/false,"hedge_level":0,"weasel_flag":false},
    ...
  ]
}"""


def extract_claims(source_items: list, title: str, llm_kwargs: dict = None) -> list:
    """从关键原话抽取原子断言。

    source_items: list[{ts, text}]（内容线传 key_sentences；通用路径传 clean_text 切句）。
    返回 list[dict]（ClaimVerification 字段子集，含 claim_id/quote/ts/factuality/scope/...）。
    失败降级 → []（不阻断主流程）。
    """
    items = [s for s in (source_items or []) if isinstance(s, dict) and s.get("text")]
    if not items:
        return []
    # 分页抽取（CLAIM_PAGE=5）+ 公式预算（PAGE_BUDGET）：每页独立调用、预算按页公式封顶，
    # 从根本上消除"长视频主张被 max_tokens 截断导致验空转"；单页截断则同预算重试一次，
    # 仍失败仅跳过该页（保持"不臆断、不阻断"），其余页正常合并去重。
    llm_kwargs = llm_kwargs or {}
    all_claims = []
    seen = set()
    n_pages = (len(items) + CLAIM_PAGE - 1) // CLAIM_PAGE
    for pi in range(0, len(items), CLAIM_PAGE):
        page = items[pi:pi + CLAIM_PAGE]
        src_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in page)
        label = f"第 {pi // CLAIM_PAGE + 1}/{n_pages} 页"
        user = (
            f"视频标题：{title}\n\n"
            f"关键原话（{label}，每页≤{CLAIM_PAGE}条）：\n{src_text}"
        )
        msgs = [
            {"role": "system", "content": _CLAIM_SYSTEM},
            {"role": "user", "content": user},
        ]
        for c in _extract_one_page(msgs, label, llm_kwargs, RESPONSE_FORMAT):
            quote = (c.get("quote") or "").strip()
            if not quote or quote in seen:
                continue
            seen.add(quote)
            ts = (c.get("ts") or "").strip()
            all_claims.append(_new_claim_dict(c, len(all_claims), ts))
    return all_claims


# ───────────────────────────────────────────────────────────────────────────
# v0.4.2 CE1+CE2: 自一致性抽主张（约束于形式信号骨架）
# ───────────────────────────────────────────────────────────────────────────
_CLAIM_SKELETON_SYSTEM = """你是验真断言抽取器，隶属于「炼真(Albedo)」流水线。
任务：从给定「关键原话骨架」中抽取原子断言（每条独立、可验证的小主张）。

规则：
1. 只从下面"骨架原话"中抽取；quote 必须逐字取自某条骨架原话（可跨相邻原话合并成一条主张，但不得添加原话里没有的事实）。
2. 若一条原话含多个独立主张，拆成多条断言。
3. 判断每条：
   - factuality: factual(可证伪事实) / opinion(主观价值判断) / mixed(前半事实后半观点)
   - scope: personal(第一人称经验"我试了…") / public(可外部验证的公开断言)
   - check_worthy: 是否"可证伪的事实主张"（personal/opinion 多为 False，public+factual 为 True）
   - hedge_level: 0(绝对,无保留) / 1(弱保留,如"比较""往往") / 2(强模糊,如"可能""大概""据说")
   - weasel_flag: 是否含水词（"研究表明""专家说""大多数人同意"等无具体出处的权威暗示）

输出保持紧凑：quote 为原话片段（≤40 字），其余字段为短枚举标签。
只输出 JSON（不要解释）：
{
  "claims": [
    {"claim_id":"c0","quote":"<原话>","ts":"mm:ss","factuality":"factual|opinion|mixed",
     "scope":"personal|public","check_worthy":true/false,"hedge_level":0,"weasel_flag":false},
    ...
  ]
}"""


def extract_claims_self_consistent(
    skeleton: list, title: str, llm_kwargs: dict = None,
    *, n_samples: int = N_SAMPLES, response_format=None,
) -> list:
    """CE1+CE2：约束于形式信号骨架，自一致性 N 次抽样 + 组合频率门槛并集抽主张。

    骨架(CE0 确定性)约束 LLM 自由发挥空间 → 方差小；N 次抽样取并集，某次抽风漏的
    别的次补上 → 主张清单更全更稳。并集去重（非投票，与 PROJECT_PLAN 禁用的判定投票不同）。

    B. 组合频率门槛并集（治漂移，v0.4.5 新增）：收集每轮每页的"主张出现"，按出现次数过滤——
      普通主张需 ≥ MIN_FREQ(=⌈N/2⌉，N=3→2) 次出现才进最终集，一次性幻觉/随机丢失直接滤掉；
      **组合豁免**：命中绝对化骗局话术(red_flags) 或 可证伪+公开+值得查(factual/public/check_worthy)
      的高风险/高置信主张即使仅出现 1 次也保留（CE3 忠实性自检已先行滤幻影，豁免不放行编造）。

    A. 分页抽取（CLAIM_PAGE=5）+ 公式预算（PAGE_BUDGET≈1320）：
      把骨架切成每页 5 条，每页独立调用、预算按"页数×单条估算×安全系数"确定封顶，
      输出长度由页大小决定，而非自动递增 max_tokens 上限（魔法数字顶蛮力，到 8192 硬上限走到头）。
      单页若仍触顶被截断 → 同预算重试一次（不抬高上限），仍失败则丢弃该页并记日志（极少发生）。

    参数：
      skeleton: build_skeleton 产出（list[{ts,text,context,...}]）
      n_samples: 自一致性抽样次数（默认 3）
      response_format: 约束解码（默认 json_object；该模型不支持 json_schema 严格模式）
    返回 list[dict]（ClaimVerification 字段子集）。失败降级 → []。
    """
    skels = [s for s in (skeleton or []) if isinstance(s, dict) and s.get("text")]
    if not skels:
        return []
    llm_kwargs = llm_kwargs or {}
    rf = response_format if response_format is not None else RESPONSE_FORMAT
    n = max(1, n_samples)
    # B. 组合频率门槛并集（治根因3 漂移）：
    #   先收集每轮每页的"主张出现"（跨轮允许重复以计频），再按出现次数过滤。
    MIN_FREQ = max(2, (n + 1) // 2)   # N=3→2；≥ 半数抽样出现才留（普通主张门槛）
    occurrences = []                  # [claim_dict(+_key)]，跨轮重复计入频率
    n_pages = (len(skels) + CLAIM_PAGE - 1) // CLAIM_PAGE
    for k in range(n):
        for pi in range(0, len(skels), CLAIM_PAGE):
            page = skels[pi:pi + CLAIM_PAGE]
            # 骨架文本：每条带上下文窗口（防跨句主张漏抽）
            skel_text = "\n".join(
                f"[{s.get('ts', '')}] {s.get('text', '')}"
                + (f"  「上下文：{' / '.join(s.get('context', []))}」" if s.get("context") else "")
                for s in page
            )
            label = f"第 {k + 1}/{n} 次抽样 · 第 {pi // CLAIM_PAGE + 1}/{n_pages} 页"
            user = (
                f"视频标题：{title}\n\n"
                f"关键原话骨架（本页抽断言的“必须覆盖范围”，每页≤{CLAIM_PAGE}条）：\n{skel_text}\n\n"
                f"（{label}，只输出本页范围内的原子断言，每页≤{CLAIM_PAGE}条；系统会跨页/跨次去重合并）"
            )
            msgs = [
                {"role": "system", "content": _CLAIM_SKELETON_SYSTEM},
                {"role": "user", "content": user},
            ]
            page_keys = set()
            for c in _extract_one_page(msgs, label, llm_kwargs, rf):
                quote = (c.get("quote") or "").strip()
                key = _norm_quote(quote)
                if not quote or key in page_keys:
                    continue  # 同页内去重（防一页内重复计频）
                page_keys.add(key)
                ts = (c.get("ts") or "").strip()
                cd = _new_claim_dict(c, len(occurrences), ts)
                cd["_key"] = key
                occurrences.append(cd)

    if not occurrences:
        return []

    # 频率统计
    freq = Counter(o["_key"] for o in occurrences)

    def _is_exempt(c: dict) -> bool:
        """组合豁免：高风险 / 高置信主张即使仅出现 1 次也保留（治"好主张仅抽中1次被误杀"）。
        - red_flags 命中绝对化骗局话术 → 最该被揪出的卖课谎言信号，必留
        - factual + public + check_worthy → 验真线最该深验的可证伪公开主张，必留
        注：Layer2 未部署时 MiniCheck 不可用，故以确定性 factuality/scope/check_worthy + red_flags
        作"高置信/高 stakes"代理；且 CE3 忠实性自检已先行滤掉字幕无依据的幻影主张，豁免不会放行编造。
        """
        if c.get("red_flags"):
            return True
        if c.get("factuality") == "factual" and c.get("scope") == "public" and c.get("check_worthy"):
            return True
        return False

    kept = [o for o in occurrences if freq[o["_key"]] >= MIN_FREQ or _is_exempt(o)]
    # 稳定排序：频率高者优先；同频时豁免者优先（输出顺序稳定，便于报告对比）
    kept.sort(key=lambda o: (-freq[o["_key"]], 0 if _is_exempt(o) else 1))
    # 跨轮去重（同一主张只留首次出现）
    seen = set()
    final = []
    for o in kept:
        if o["_key"] in seen:
            continue
        seen.add(o["_key"])
        o.pop("_key", None)
        final.append(o)
    # 重排 claim_id 连续（c0..c{n-1}）
    for i, o in enumerate(final):
        o["claim_id"] = f"c{i}"
    return final


def _extract_one_page(msgs: list, label: str, llm_kwargs: dict, rf: dict) -> list:
    """抽一页主张（解析 JSON），对付空响应 + 截断，绝不抬高 max_tokens 上限。

    - 正常：call_llm_json 已内含空响应/解析失败重试（指数退避），返回合法 dict。
    - 截断（call_llm_json 仍解析失败抛错）：从 raw 续写游标——raw_decode 提取已完成 claim 对象，
      让模型从最后 claim_id 续写剩余主张（同预算、不重跑整页）→ 合并返回。
    - 续写仍失败：同预算重试一次（提示补全合法 JSON）；仍失败则丢弃该页返回 []
      （绝不替模型脑补结尾，也绝不无限加 max_tokens）。
    """
    base_user = msgs[1]["content"]
    for attempt in range(PAGE_RETRY + 1):
        try:
            data = call_llm_json(msgs, max_tokens=PAGE_BUDGET, response_format=rf, **llm_kwargs)
        except Exception as e:
            logger.warning("extract_claims 分页 %s 调用失败（第 %d 次）：%s", label, attempt + 1, e)
            if attempt < PAGE_RETRY:
                # 截断兜底：从 raw 续写恢复已完成对象（续写游标，不抬高上限）
                try:
                    raw = call_llm(msgs, max_tokens=PAGE_BUDGET, response_format=rf, **llm_kwargs)
                except Exception:
                    raw = ""
                partial = _recover_complete_claims(raw) if raw else []
                if partial:
                    last_id = (partial[-1].get("claim_id") or "")
                    resumed = _resume_page(base_user, rf, llm_kwargs, last_id, label)
                    if resumed is not None:
                        return partial + resumed
                # 续写失败 → 同预算重试（提示补全合法 JSON）
                msgs = [
                    msgs[0],
                    {"role": "user", "content": base_user
                     + "\n\n（上一次输出被截断或非法，请只输出完整、合法的 JSON，不要任何解释或省略。）"},
                ]
                time.sleep(2 ** attempt)
                continue
            logger.warning("extract_claims 分页 %s 抽取失败，丢弃该页", label)
            return []
        # 正常返回
        return data.get("claims") or []
    return []


def _recover_complete_claims(raw: str) -> list:
    """从截断的 JSON 文本中提取已完整序列化的 claim 对象（位于 "claims":[...] 内）。

    用 json.JSONDecoder.raw_decode 逐个解码，遇到半截对象即停；返回已完成对象列表。
    若整体可解析（未截断），extract_json_block 已先行处理，这里主要兜底截断情形。
    """
    if not raw or not raw.strip():
        return []
    m = re.search(r'"claims"\s*:\s*\[', raw)
    if not m:
        return []
    i = m.end()
    dec = json.JSONDecoder()
    claims = []
    n = len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n,":
            i += 1
        if i >= n or raw[i] == "]":
            break
        if raw[i] != "{":
            break
        try:
            obj, end = dec.raw_decode(raw, i)
            claims.append(obj)
            i = end
        except json.JSONDecodeError:
            break  # 半截对象，停止
    return claims


def _resume_page(base_user: str, rf: dict, llm_kwargs: dict, last_id: str, label: str) -> list:
    """续写：让模型从 last_id 之后继续输出剩余主张（同预算、不抬高上限）。

    返回续写出的 claims 列表（已完成的剩余对象），失败返回 None。
    """
    sys_msg = {
        "role": "system",
        "content": (
            "你是验真断言抽取器。上一次输出在 claim_id=%s 之后被截断。"
            "请只输出该条之后的【剩余】原子断言，沿用相同 JSON 格式（仅含新增 claims 数组），"
            "不要重复已输出的主张，不要任何解释。" % (last_id or "")
        ),
    }
    user_msg = {
        "role": "user",
        "content": base_user
        + f"\n\n（续写任务：从 claim_id={last_id} 之后继续，只输出剩余未抽的原子断言。）",
    }
    try:
        raw = call_llm([sys_msg, user_msg], max_tokens=PAGE_BUDGET, response_format=rf, **llm_kwargs)
        data = extract_json_block(raw)
        if data is not None:
            return data.get("claims") or []
    except Exception as e:
        logger.warning("extract_claims 分页 %s 续写失败：%s", label, e)
    return None


# ───────────────────────────────────────────────────────────────────────────
# v0.4.2 CE3: 确定性忠实性自检（补最大科学漏洞，零 LLM）
# ───────────────────────────────────────────────────────────────────────────
def _norm_quote(q: str) -> str:
    """主张归一化键（去上下文装饰+去空白/分隔符+首尾标点），用于自一致性去重与子串匹配。

    v0.4.9 修复：LLM 有时把骨架「上下文：A / B / C」装饰原样带回 quote，
    导致同一主张的"纯文本版"与"带上下文前缀版"归一化后 key 不同、漏去重（RUN1 出现 3 份同源主张）。
    此处先剥除该装饰（整块 + 裸露前缀），再统一去空白与骨架用的"/"分隔符，让变体归并为同一键。
    """
    q = (q or "").strip()
    # 剥除骨架「上下文：…」整块装饰（LLM 误回声）
    q = re.sub(r"「上下文：.*?」", "", q)
    # 剥除裸露的 上下文：A/B/C 前缀（无书名号情形）
    q = re.sub(r"上下文[:：][^\s「]*?(?:/[^\s「]*?)*", "", q)
    q = re.sub(r"\s+", "", q)        # 去所有空白
    q = q.replace("/", "")           # 去骨架用的 "/" 分隔符（A/B 与 A B 视为同键）
    q = q.strip("，。！？；：、,.;:!? ")
    return q


def _substring_match_ts(quote: str, subs: list) -> Optional[str]:
    """主张 quote 与字幕逐句做子串/模糊匹配，命中返回首句 ts，否则 None。

    处理跨句主张：quote 按标点拆子句，每子句（>=3字）须能在字幕某句找到 → 取首子句 ts。
    """
    norm_quote = _norm_quote(quote)
    if len(norm_quote) < 4:
        return None
    # 预归一化字幕
    norm_subs = [(s.get("ts", ""), _norm_quote(s.get("text", ""))) for s in subs]
    # 整句子串匹配
    for ts, ntext in norm_subs:
        if ntext and norm_quote in ntext:
            return ts
    # 跨句：拆子句分别匹配（允许分散在不同句）
    clauses = [c for c in re.split(r"[，。！？；：、,.;:!?]", norm_quote) if len(c) >= 3]
    if len(clauses) >= 2:
        matched_first_ts = None
        all_hit = True
        for cl in clauses:
            hit = False
            for ts, ntext in norm_subs:
                if cl in ntext:
                    if matched_first_ts is None:
                        matched_first_ts = ts
                    hit = True
                    break
            if not hit:
                all_hit = False
                break
        if all_hit and matched_first_ts is not None:
            return matched_first_ts
    return None


def faithfulness_check(claims: list, subtitle_lines: list) -> tuple:
    """CE3 确定性忠实性自检：每条主张 quote 与字幕全文子串/模糊匹配。

    仅做「标记」，不做硬删：命中 → faithfulness="grounded" + anchor_ts（溯源）；
    未命中 → "ungrounded"（确定性弱信号）。最终去留由 Layer0.5 guard_claim_faithfulness
    的 LLM NLI 裁决（避免子串匹配的假阴性把忠实改写主张误删；抽主张提示词允许"微调措辞"）。
    零 LLM、确定性。返回 (claims, ungrounded_count)。
    """
    claims = claims or []
    subs = [s for s in (subtitle_lines or []) if isinstance(s, dict) and s.get("text")]
    if not subs:
        # 无字幕可查 → 全部标 grounded（Layer0.5 无原文亦保留），交由下游
        for c in claims:
            c.setdefault("faithfulness", "grounded")
        return claims, 0
    ungrounded = 0
    for c in claims:
        ts = _substring_match_ts(c.get("quote", ""), subs)
        if ts is not None:
            c["faithfulness"] = "grounded"
            c["anchor_ts"] = ts
        else:
            c["faithfulness"] = "ungrounded"
            ungrounded += 1
    return claims, ungrounded


def _is_water_claim(quote: str) -> bool:
    """确定性水主张检测（D 任务 #163）：命中任一即非可证伪事实主张，AE1 闸门强制剔除。

    - 序数/过渡句（第一/第二/首先/其次/最后/第一步…）
    - 定义性碎片（"X就是Y"/"所谓X"/"是一种"…）
    - 纯话题词/碎片：无断言谓词、无数字/中文数量词、无比较 → 只是名词短语
    保留含断言谓词/数字/比较的真事实或意见主张，不误杀。
    """
    q = (quote or "").strip()
    if not q:
        return True
    n = re.sub(r"[\s，。！？、,.;:!?“”\"'（）()【】\[\]~～]", "", q)
    if len(n) < 5:
        return True
    # 1) 序数 / 过渡句
    if re.match(r"^(第一|第二|第三|第四|第五|第六|首先|其次|然后|接着|最后|其一|其二|其三|其四|"
                r"第一点|第二点|第一步|第二步|第三步|总结一下|总而言之|接下来|话说回来|"
                r"简单来说|具体来讲|举个例子|比如|换言之|换句话说)", n):
        return True
    # 2) 定义性碎片（"X就是Y"等）
    if re.search(r"(就是|是一个|是一种|是一|即为|所谓|指的是|名叫|称为|也就是)", n):
        return True
    # 3) 纯话题词/碎片：无断言谓词、无数量、无比较
    _quants = re.compile(r"[\d零一二三四五六七八九十百千万亿%|％倍]")
    # 谓词指标：逐词匹配（多字谓词 + 安全的单字评价词）。
    # 故意剔除易碰撞单字（能/有/会/是/行：智能·会议·行业·是否 等大量非谓词场景），
    # 用元组逐 token 匹配，避免 set("成为") 把"能"单字泄露、把"AI智能体赛道"误判含谓词而放行。
    _predicates = (
        # 多字谓词（断言/评价动词）
        "成为", "能够", "拥有", "可以", "应该", "需要", "值得", "达到", "超过", "等于",
        "大于", "小于", "多于", "少于", "增加", "减少", "提升", "下降", "上涨", "下跌",
        "属于", "包括", "包含", "证明", "说明", "表示", "指出", "认为", "建议", "带来",
        "导致", "造成", "引发", "获得", "拿下", "卖出", "买入", "成功", "失败", "领先",
        "落后", "保持", "靠谱", "便宜", "稳定", "安全", "危险", "有效", "无效", "合理",
        "离谱", "清晰", "混乱", "准确", "模糊", "明显", "突出", "重要", "必要", "关键",
        "合适", "可行", "核心",
        # 安全单字评价词
        "高", "低", "好", "差", "强", "弱", "快", "慢", "优", "劣", "真", "假", "贵",
        "难", "易", "稳", "安", "危", "效", "清", "准", "明", "重", "合", "离", "坑", "值", "火",
    )
    has_pred = any(p in n for p in _predicates)
    has_quant = bool(_quants.search(n))
    has_cmp = bool(re.search(r"(倍于|比|更|较|同比|环比|相比|以上|以下|之内|之间|高于|低于|优于|劣于)", n))
    if not has_pred and not has_quant and not has_cmp:
        return True
    return False


# ───────────────────────────────────────────────────────────────────────────
# Layer 0.5: 断言忠实度核查（防 LLM 瞎编）—— 最关键防坑层（V3 遗漏3）
# ───────────────────────────────────────────────────────────────────────────
_GUARD_SYSTEM = """你是断言忠实性检查器。给定一组"抽取断言"和"视频字幕原文"，
对每条断言判断：它陈述的内容是否能被字幕原文直接支撑（蕴含）？
- supported=true：字幕里有对应内容，或可由字幕合理推出
- supported=false：字幕里找不到任何依据，疑似抽取器编造/臆测（应丢弃）

只输出 JSON（不要解释）：
{
  "results": [
    {"claim_id":"c0","supported":true/false},
    ...
  ]
}"""


def guard_claim_faithfulness(claims: list, subtitle_lines: list, llm_kwargs: dict = None):
    """Layer 0.5：每条抽取断言 vs 字幕原文 NLI，ungrounded 的直接丢弃（防污染）。

    无字幕（通用路径）→ 无法核查，全部保留（faithfulness 保持 grounded 默认）。
    返回 (kept_claims, n_dropped)。LLM 失败 → 全部保留（降级不丢数据）。
    """
    claims = claims or []
    if not claims:
        return [], 0
    subs = subtitle_lines or []
    if not subs:
        return claims, 0  # 无原文可查，保留

    subs_text = "\n".join(f"[{s.get('ts', '')}] {s.get('text', '')}" for s in subs)
    claims_text = "\n".join(f"{c['claim_id']}: {c['quote']}" for c in claims)
    user = f"字幕原文：\n{subs_text}\n\n待核查断言：\n{claims_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _GUARD_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=2000,
            **(llm_kwargs or {}),
        )
        sup_map = {r.get("claim_id"): bool(r.get("supported", True))
                   for r in (data.get("results") or [])}
        kept, dropped = [], 0
        for c in claims:
            sup = sup_map.get(c["claim_id"])  # None = guard 未返回（响应截断等）
            if sup is None:
                # 回退 CE3 确定性子串判定：guard 漏覆盖时不默认放行、也不误杀
                sup = (c.get("faithfulness") == "grounded")
            if sup:
                c["faithfulness"] = "grounded"  # 以 LLM NLI 裁决为权威
                kept.append(c)
            else:
                c["faithfulness"] = "ungrounded"
                dropped += 1  # 丢弃（不进入后续验真，避免披"已核查"外衣）
        return kept, dropped
    except Exception:
        return claims, 0  # 降级：保留全部


# ───────────────────────────────────────────────────────────────────────────
# Layer 1a: 话术识别（规则，不联网）：绝对化骗局话术 + 水词 + 模糊语（V3 遗漏6）
# ───────────────────────────────────────────────────────────────────────────
def detect_rhetoric(claims: list, clean_text: str = "") -> list:
    """规则识别每条断言的话术特征（消费形式线单一来源规则库 apply_rhetoric_rules）。

    就地写入 red_flags / weasel_flag / hedge_level。返回全局命中的 red_flags 标签集合（去重）。
    v0.4.0 起：修辞规则正则统一归 core.form_track，此处仅消费，避免重复维护。
    """
    claims = claims or []
    blob = clean_text or ""
    global_flags = set()
    for c in claims:
        red_flags, weasel, lvl = apply_rhetoric_rules(c.get("quote", ""), blob)
        c["red_flags"] = red_flags
        global_flags.update(red_flags)
        if weasel:
            c["weasel_flag"] = True
        c["hedge_level"] = max(c.get("hedge_level", 0) or 0, lvl)
    return sorted(global_flags)


# ───────────────────────────────────────────────────────────────────────────
# Layer 1b: 自相矛盾检测（两两 NLI，逻辑必然不实，不联网）（V3 遗漏1）
# ───────────────────────────────────────────────────────────────────────────
_SC_SYSTEM = """你是逻辑矛盾检测器。给定一组断言（带 id 与原文），
找出哪些「对」互相矛盾——即两句话不能同时为真（例如一个说免费、另一个说收费；
一个说日入过万、另一个说根本没赚到）。

只输出 JSON（不要解释）：
{
  "contradictions": [
    {"a_id":"c0","b_id":"c1","explanation":"一句话说明矛盾点"}
  ]
}
若无矛盾，返回 {"contradictions":[]}。"""


def detect_self_contradiction(claims: list, llm_kwargs: dict = None) -> list:
    """两两 NLI 检测自相矛盾，就地写 claim.contradicts_with + accuracy=contradicted。
    返回矛盾对列表（供报告）。失败降级 → []。
    """
    claims = claims or []
    if len(claims) < 2:
        return []
    claims_text = "\n".join(f"{c['claim_id']}: {c['quote']}" for c in claims)
    user = f"断言列表：\n{claims_text}"
    try:
        data = call_llm_json(
            [{"role": "system", "content": _SC_SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=2000,
            **(llm_kwargs or {}),
        )
        pairs = data.get("contradictions") or []
        by_id = {c["claim_id"]: c for c in claims}
        out = []
        for p in pairs:
            aid, bid = p.get("a_id"), p.get("b_id")
            if aid not in by_id or bid not in by_id or aid == bid:
                continue
            a, b = by_id[aid], by_id[bid]
            a["contradicts_with"].append({"claim_id": bid, "ts": b.get("ts", "")})
            b["contradicts_with"].append({"claim_id": aid, "ts": a.get("ts", "")})
            a["accuracy"] = "contradicted"
            b["accuracy"] = "contradicted"
            a["reasoning"] = p.get("explanation", "视频自相矛盾")
            b["reasoning"] = p.get("explanation", "视频自相矛盾")
            out.append({"a_id": aid, "a_ts": a.get("ts", ""),
                        "b_id": bid, "b_ts": b.get("ts", ""),
                        "explanation": p.get("explanation", "")})
        return out
    except Exception:
        return []


# ───────────────────────────────────────────────────────────────────────────
# Layer 1c: 时效标记（规则，不联网）：verified_date + validity_class（V3 遗漏2）
# ───────────────────────────────────────────────────────────────────────────
def tag_recency(claims: list, verified_date: str = None) -> None:
    """就地写 verified_date（今日）+ validity_class（命中限时关键词→timeboxed，默认 evergreen）。"""
    vd = verified_date or date.today().isoformat()
    for c in (claims or []):
        c["verified_date"] = vd
        c["validity_class"] = "timeboxed" if _TIMEBOXED_KW.search(c.get("quote", "")) else "evergreen"


# ───────────────────────────────────────────────────────────────────────────
# Layer 2: 联网深验（MiniCheck 本地）—— 接口留好，沙箱标 unverified（V3 遗漏5 保守）
# ───────────────────────────────────────────────────────────────────────────
def verify_claims_web(claims: list, llm_kwargs: dict = None, subtitle_lines: list = None) -> None:
    """Layer 2 逐条验真（mDeBERTa-XNLI 本地部署后启用，TT6 实质）。

    真实路径：对 check_worthy 且 scope=public 且 factuality=factual 的断言调 mDeBERTa-XNLI
    逐条 supported/contradicted（见 core/minicheck_verify.py）。
    subtitle_lines（视频字幕原文）作为证据语料 docs，避免用断言自身当证据导致自指误判。
    权重缺失 / 未装 → 保守标 unverified，并**明确告警**（E 任务 #164：消除静默降级误判）。
    """
    try:
        from core.minicheck_verify import verify_claims, is_available, LOCAL_DIR
        layer2_ran = verify_claims(claims, corpus=subtitle_lines)
        if layer2_ran:
            return
        # 模型未实际跑：区分"无目标主张"（正常）与"权重缺失"（需告警）
        if not is_available():
            logger.warning(
                "⚠️ Layer2 深度验真未启用：transformers/torch 不可用，仅 Layer1 不联网快筛；"
                "结论为'未验真'默认值，非真实验真结论。"
            )
        elif not os.path.exists(LOCAL_DIR):
            logger.warning(
                "⚠️ Layer2 深度验真未启用：权重目录缺失 %s；所有公开事实主张标 unverified，"
                "结论为'未验真'默认值，非真实验真结论。权重部署到该目录后即自动启用。",
                LOCAL_DIR,
            )
        # 其余情况（模型在但无 targets 可验）属正常，不告警
    except Exception as e:
        logger.warning("⚠️ Layer2 深度验真异常降级 unverified：%s", e)
    # 降级：保守标 unverified（已 contradicted 的保矛盾结论）
    for c in (claims or []):
        if c.get("accuracy") == "contradicted":
            continue  # 自相矛盾已定论，不被 unverified 覆盖
        c["accuracy"] = "unverified"
        c["confidence"] = 0.0
        c["epistemic_status"] = "unverified"
        if not c.get("reasoning"):
            c["reasoning"] = LAYER2_NOTE


# ───────────────────────────────────────────────────────────────────────────
# 聚合：文档级结论（落熔知字段 + 报告）
# ───────────────────────────────────────────────────────────────────────────
def aggregate(claims: list, dropped_count: int = 0, persuasion_polish: float = 0.0, dropped_audit: list = None) -> dict:
    """聚合逐条结果为文档级摘要。

    信任分(0-1)保守：未验证不过高（V3 遗漏5）。矛盾→0.3，话术→0.4，
    个人经验/观点→0.5，可证伪公开事实→0.6；上限 0.6（公开事实理论上可外部验证，
    信任应高于无法验证的主观经验）。
    severity: alert(矛盾) / warn(话术) / ok。
    persuasion_polish(G1 反向桥)：高说服包装 + 证据未验证 → 额外谨慎（轻微下调信任）。
    """
    claims = claims or []
    n = len(claims)
    n_contradicted = sum(1 for c in claims if c.get("accuracy") == "contradicted")
    n_redflag = sum(1 for c in claims if c.get("red_flags"))
    n_timeboxed = sum(1 for c in claims if c.get("validity_class") == "timeboxed")
    is_personal = any(c.get("scope") == "personal" for c in claims)
    has_factual_public = any(
        c.get("factuality") == "factual" and c.get("scope") == "public" for c in claims
    )

    if n_contradicted > 0:
        severity = "alert"
        trust = 0.3
        epistemic_status = "unverified"
    elif n_redflag > 0:
        severity = "warn"
        trust = 0.4
        epistemic_status = "unverified"
    elif not has_factual_public:
        severity = "ok"
        trust = 0.5  # 个人经验/观点无法外部验证，信任保守（不高于可证伪公开事实）
        epistemic_status = "unverified"
    else:
        severity = "ok"
        trust = 0.6  # 可证伪公开事实主张理论上可外部验证，信任略高（仍受未联网深验限制，上限 0.6）
        epistemic_status = "unverified"

    # G1 反向桥：高说服包装 + 未验证证据 → 额外谨慎（真相错觉防御）
    polish_note = ""
    if persuasion_polish >= 0.7 and severity == "ok":
        trust = max(0.2, round(trust * 0.85, 2))
        polish_note = "高说服包装 + 证据未验证，已额外下调信任（真相错觉防御）"

    contradictions = []
    for c in claims:
        for other in c.get("contradicts_with", []):
            contradictions.append({
                "claim_id": c.get("claim_id"), "ts": c.get("ts"),
                "with_claim_id": other.get("claim_id"), "with_ts": other.get("ts"),
            })

    recency_note = (
        "含限时断言（平台规则/价格/版本类），结论有时效，建议复核后谨慎采用。"
        if n_timeboxed else ""
    )
    if polish_note:
        recency_note = (recency_note + "；" if recency_note else "") + polish_note

    return {
        "n_claims": n,
        "n_dropped": dropped_count,
        "n_contradicted": n_contradicted,
        "n_redflag": n_redflag,
        "n_timeboxed": n_timeboxed,
        "is_personal": is_personal,
        "severity": severity,
        "trust_score": trust,
        "epistemic_status": epistemic_status,
        "contradictions": contradictions,
        "recency_note": recency_note,
        "persuasion_polish": persuasion_polish,
        "red_flags": sorted({f for c in claims for f in c.get("red_flags", [])}),
        "dropped_audit": dropped_audit or [],
    }


# ───────────────────────────────────────────────────────────────────────────
# 编排入口
# ───────────────────────────────────────────────────────────────────────────
def _run_truth_track(
    inp,
    *,
    key_sentences: list = None,
    subtitle_lines: list = None,
    clean_text: str = "",
    llm_kwargs: dict = None,
    persuasion_polish: float = 0.0,
    video_id: str = "",
    cache_enabled: bool = True,
    form_track: dict = None,
    content_track: dict = None,
) -> dict:
    """验真主流程（v0.4.2：CE0 形式信号骨架 → CE1+CE2 自一致性抽主张 →
    CE3 确定性忠实性自检 → CE4 缓存 → Layer0.5~Layer3 确定性逐层验真）。

    参数：
      key_sentences: 内容线关键原话 [{ts, text}]（无字幕时退化抽取源）
      subtitle_lines: 字幕原文（CE0 骨架 + CE3/Layer0.5 核查用）
      clean_text: 净化后全文（话术规则 + 无字幕兜底抽取）
      persuasion_polish: 形式线 G1 反向桥（高包装+未验证证据→额外谨慎）
      video_id: Nigredo bvid（CE4 缓存键；空则跳过缓存）
      cache_enabled: CE4 缓存开关（默认开）
    返回 {claims: list[dict], truth_track: dict, dropped: int}。整体不抛。
    """
    key_sentences = key_sentences or []
    subtitle_lines = subtitle_lines or []
    llm_kwargs = llm_kwargs or {}

    # 验真配置指纹（v0.4.7）：模型/逻辑/LLM 任一变化 → 旧缓存自动失效
    sig = compute_verify_sig()

    # ── CE0 形式信号骨架（确定性，零 LLM，<1s）──
    skeleton = []
    if subtitle_lines:
        try:
            skeleton = build_skeleton(
                subtitle_lines, top_k=TOP_K_SKELETON,
                clean_text=clean_text, danmaku=getattr(inp, "danmaku", None),
            )
        except Exception:
            skeleton = []

    # ── CE4 缓存优先（复查直接复用最终主张集，完全确定性复现）──
    cached = None
    if cache_enabled and video_id:
        cached = load_claim_cache(video_id, sig)

    if cached is not None:
        kept = cached["claims"]
        ce_dropped = 0
        l0_dropped = 0
        claims_ae1_dropped = 0
        dropped_audit = cached.get("dropped_audit") or []
    else:
        dropped_audit = []
        # ── CE1+CE2 自一致性抽主张（约束骨架；无骨架退化旧路径）──
        if skeleton:
            claims = extract_claims_self_consistent(
                skeleton, getattr(inp, "title", "") or "", llm_kwargs,
                n_samples=N_SAMPLES, response_format=RESPONSE_FORMAT,
            )
        else:
            if key_sentences:
                source_items = [{"ts": k.get("ts", ""), "text": k.get("text", "")} for k in key_sentences]
            else:
                source_items = [{"ts": "", "text": s.strip()}
                                 for s in re.split(r"[。！？\n]+", clean_text or "") if s.strip()][:20]
            claims = extract_claims(source_items, getattr(inp, "title", "") or "", llm_kwargs)
        # ── AE1 可证伪性闸门（对标 ClaimBuster checkworthiness）：
        #    仅保留 check_worthy=True 的可证伪事实主张进入验真管线；
        #    纯观点/水词/主观感受（"接下来全程干货""一听就懂"）check_worthy=False → 剔除，
        #    不占 Layer0.5 NLI / Layer1~2 验真预算，不污染判定。
        claims_ae1_dropped = 0
        if claims:
            water = [c for c in claims if _is_water_claim(c.get("quote", ""))]
            if water:
                logger.info("AE1 确定性水主张过滤：剔除 %d 条水词/过渡句/碎片", len(water))
                for c in water:
                    dropped_audit.append({
                        "quote": c.get("quote", ""), "ts": c.get("ts", ""),
                        "stage": "AE1_water",
                        "reason": "水词/过渡句/定义碎片（非可证伪事实主张，验真线跳过）",
                    })
            non_water = [c for c in claims if not _is_water_claim(c.get("quote", ""))]
            non_checkworthy = [c for c in non_water if not c.get("check_worthy")]
            for c in non_checkworthy:
                dropped_audit.append({
                    "quote": c.get("quote", ""), "ts": c.get("ts", ""),
                    "stage": "AE1_noncheckworthy",
                    "reason": "非可证伪事实主张（观点/主观感受，验真线跳过）",
                })
            filtered = [c for c in non_water if c.get("check_worthy")]
            claims_ae1_dropped = len(non_water) - len(filtered) + len(water)
            claims = filtered
            if claims_ae1_dropped:
                logger.info("AE1 可证伪性闸门：剔除 %d 条非可证伪/水主张", claims_ae1_dropped)
        # ── CE3 确定性忠实性自检（标记 grounded/ungrounded，不硬删）──
        kept, ce_dropped = faithfulness_check(claims, subtitle_lines)
        # ── C 任务 #162：主张 ts 回填真实值（溯源断点修复）──
        # faithfulness_check 已用 _substring_match_ts 算出 anchor_ts（真实字幕位置），
        # 但主张主字段 ts 常因 LLM 不可靠填 00:00；此处确定性回填，保证报告溯源可点。
        for c in (kept or []):
            t = (c.get("ts") or "").strip()
            if (not t or t == "00:00") and c.get("anchor_ts"):
                c["ts"] = c["anchor_ts"]
                try:
                    c["start"] = _ts_to_sec(c["ts"])
                except Exception:
                    pass
        # ── Layer0.5 LLM 防瞎编（NLI 裁决，回退 CE3 确定性判定）──
        _pre_guard = list(kept or [])
        kept, l0_dropped = guard_claim_faithfulness(kept, subtitle_lines, llm_kwargs)
        _kept_ids = {id(x) for x in kept}
        for c in _pre_guard:
            if id(c) not in _kept_ids:
                dropped_audit.append({
                    "quote": c.get("quote", ""), "ts": c.get("ts", ""),
                    "stage": "L0.5_ungrounded",
                    "reason": "字幕中找不到依据（防瞎编 NLI 裁决丢弃）",
                })
        # ── Layer1~Layer3（仅非缓存路径执行；缓存命中直接复用，保证复现一致）──
        detect_rhetoric(kept, clean_text)
        detect_self_contradiction(kept, llm_kwargs)
        tag_recency(kept)
        # ── Layer2 逐条验真（字幕作证据）──
        verify_claims_web(kept, llm_kwargs, subtitle_lines)
        # ── Layer3 联网核查框架（无 key 诚实降级标"待联网核查"）──
        web_verify_claims(kept)
        # ── CE4 写缓存（必须在 Layer1~3 全部完成后！冻结含验真结论的最终主张集
        #    + 形式线 form_track；复查不重抽/不重验/不重算形式线，完全确定性复现。
        #    v0.4.7 起带 verify_sig，配置变化自动失效，无需手动 rm。）──
        if cache_enabled and video_id and kept:
            save_claim_cache(video_id, kept, form_track=form_track,
                             content_track=content_track, verify_sig=sig,
                             dropped_audit=dropped_audit)

    truth_track = aggregate(kept, ce_dropped + l0_dropped + claims_ae1_dropped,
                             persuasion_polish=persuasion_polish, dropped_audit=dropped_audit)
    return {"claims": kept, "truth_track": truth_track,
            "dropped": ce_dropped + l0_dropped + claims_ae1_dropped,
            "dropped_audit": dropped_audit}


# ── 小工具 ──
def _new_claim_dict(c: dict, idx: int, ts: str) -> dict:
    """从 LLM 抽出的单条 claim 构造 ClaimVerification 字段子集（含 v0.4.2 新增 anchor_ts/web_status）。"""
    return {
        "claim_id": f"c{idx}",
        "quote": (c.get("quote") or "").strip(),
        "ts": ts,
        "start": _ts_to_sec(ts),
        "factuality": _coerce(c.get("factuality"), ("factual", "opinion", "mixed"), "factual"),
        "scope": _coerce(c.get("scope"), ("personal", "public"), "public"),
        "check_worthy": bool(c.get("check_worthy", False)),
        "hedge_level": _int(c.get("hedge_level"), 0),
        "weasel_flag": bool(c.get("weasel_flag", False)),
        "faithfulness": "grounded",
        "anchor_ts": "",
        "web_status": "",
        "accuracy": "",
        "red_flags": [],
        "contradicts_with": [],
        "validity_class": "",
        "verified_date": "",
        "confidence": 0.0,
        "epistemic_status": "",
        "evidence": "",
        "reasoning": "",
        "is_visual_claim": False,
        "cross_modal_contradiction": False,
        "creator_id": "",
        "creator_rep_delta": 0.0,
    }


def _coerce(v, allowed, default):
    v = (v or "").strip().lower()
    return v if v in allowed else default


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default
