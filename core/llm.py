"""Albedo (Lian Zhen) · LLM 调用封装 (C3 复用)

对齐 熔知 search_engine.answer._call_llm_api 约定：
  - env: KB_LLM_BASE_URL / KB_LLM_API_KEY / KB_LLM_MODEL
  - 默认 base_url = https://api.deepseek.com/v1, model = deepseek-chat
  - OpenAI 兼容 /chat/completions 接口，temperature=0 确定性输出
  - 结构化输出借鉴 熔知 utils.llm_helpers.extract_json_block 的花括号深度匹配容错

将来 熔知 改了这套约定，这里需同步改（已在 PROJECT_PLAN §5.2 标注）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

# 若项目根存在 .env，优先加载（不强制依赖 python-dotenv）
def _load_env_file():
    """兼容无 python-dotenv 的环境：手动解析项目根 .env。

    仅当变量尚未在环境中时写入（与 load_dotenv 默认 override=False 一致，
    即显式环境变量优先于 .env）。沙箱 pip 被 SSL 拦截无法装 dotenv 时，
    这一兜底保证 core 仍能读到 .env 里的 KB_LLM_* 配置。
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return
    except Exception:
        pass
    # 手动兜底：path = 项目根/.env（core/llm.py 的上两级）
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k.startswith("export "):
                    k = k[len("export "):]
                if not k:
                    continue
                # 去引号（' 或 " 包裹）
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                if k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_env_file()

import requests

logger = logging.getLogger("albedo.llm")


class EmptyResponseError(RuntimeError):
    """LLM 返回 HTTP 200 但 content 为空（DeepSeek 服务压力下的瞬时故障，非业务错误）。"""


class TruncatedResponseError(RuntimeError):
    """LLM 返回 finish_reason=length：输出被 max_tokens 截断。

    此时 content 非空但残缺（无完整 JSON），应走续写游标(resume)而非重跑整页——
    否则 call_llm_json 会浪费多次整页重试才放弃。
    """


LLM_BASE_URL = os.environ.get("KB_LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("KB_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("KB_LLM_MODEL", "deepseek-chat")


def call_llm(
    messages: list,
    *,
    base_url: str = None,
    api_key: str = None,
    model: str = None,
    max_tokens: int = 2048,
    timeout: int = 120,
    seed: int = None,
    response_format: dict = None,
) -> str:
    """调用 OpenAI 兼容 Chat API，返回模型回复文本。"""
    base_url = (base_url or LLM_BASE_URL).rstrip("/")
    api_key = api_key or LLM_API_KEY
    model = model or LLM_MODEL
    if not api_key:
        raise RuntimeError(
            "未配置 LLM API。请设置环境变量 KB_LLM_API_KEY（或项目根 .env 文件）。"
        )
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    # 全局 max_tokens 覆盖（仅测试对照用）：推理模型（如 deepseek-v4-flash）的 max_tokens
    # 约束「隐藏推理 + 最终答案」的总额，固定预算会被推理吃光 → finish_reason=length 把答案截断/清空。
    # 设 ALBEDO_LLM_MAX_TOKENS_OVERRIDE=8000 可临时抬高上限，便于与 deepseek-chat 公平对照。
    # 正常生产路径不设置此变量，沿用各调用点自身的预算（PAGE_BUDGET 等）。
    _ovr = os.environ.get("ALBEDO_LLM_MAX_TOKENS_OVERRIDE")
    if _ovr:
        try:
            _ovr_n = int(_ovr)
            if _ovr_n > 0:
                body["max_tokens"] = _ovr_n
        except ValueError:
            pass
    if seed is not None:
        body["seed"] = seed
    if response_format is not None:
        # OpenAI / DeepSeek 兼容：json_object 强制合法 JSON 输出（要求消息含 "json" 字样）
        body["response_format"] = response_format
    resp = requests.post(
        f"{base_url}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    content = (choice.get("message") or {}).get("content") or ""
    finish = choice.get("finish_reason")
    if not content.strip():
        # DeepSeek 服务压力大时返回 HTTP 200 + 空 content（finish_reason 可能为 null/stop），
        # 属瞬时故障，抛错交由 call_llm_json / 调用方重试，而非把空串当正常结果写入。
        raise EmptyResponseError(
            f"LLM 返回空 content（finish_reason={finish}）；视为瞬时故障，交由上层重试。"
        )
    if finish == "length":
        # 输出被 max_tokens 截断 → 抛截断错误，交由 _extract_one_page 走续写游标，
        # 避免 call_llm_json 反复重跑整页（浪费 key + 增加丢页率）。
        raise TruncatedResponseError(
            f"LLM 输出被截断（finish_reason=length）；走续写游标而非整页重试。"
        )
    return content


def _strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 代码围栏。"""
    t = text.strip()
    if t.startswith("```"):
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1:]
        end = t.rfind("```")
        if end != -1:
            t = t[:end]
    return t.strip()


def _find_first_bracket(text: str) -> int:
    """返回第一个 { 或 [ 的位置；都没有返回 -1。"""
    bi, ai = text.find("{"), text.find("[")
    cands = [i for i in (bi, ai) if i != -1]
    return min(cands) if cands else -1


def _try_parse(block: str):
    """尝试解析 JSON，失败则去掉尾部逗号后重试。"""
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([\]}])", r"\1", block)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def extract_json_block(text):
    """从 LLM 返回文本中提取并解析 JSON（对象或数组）。

    解析策略（不修补残缺答案，完整性由调用方保障）：
      1. 直接 json.loads
      2. 去 ```json 代码围栏后重试
      3. 按括号深度找最外层 { 或 [，完整闭合则解析（去尾部逗号）
    返回 dict / list；无法解析时返回 None。

    完整性保障来自调用方：response_format=json_object 强制合法 JSON 输出，
    且调用方通过分页 + 按页公式预算（PAGE_BUDGET）确保输出不被截断，故此处不做截断修复。
    """
    if not text:
        return None
    text = text.strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 去代码围栏
    fenced = _strip_code_fence(text)
    if fenced is not text:
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            text = fenced

    # 3. 找最外层完整 JSON
    start = _find_first_bracket(text)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    json_end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_end == -1:
        # 无完整闭合块（答案被截断 / 非 JSON 文本）→ 不修补残缺答案，
        # 交由 call_llm_json 的预算递增重试；仍解析失败则上层抛错。
        return None
    block = text[start:json_end]
    return _try_parse(block)


_MAX_JSON_RETRIES = 3


def call_llm_json(messages: list, **kwargs) -> dict:
    """call_llm + extract_json_block 组合，带空响应 / 解析失败重试（指数退避）。

    所有调用方（形式线 FT1~FT5 / 验真线 防瞎编 / 矛盾检测 / 抽主张）自动获得韧性：
    DeepSeek 偶发空 content 或截断 → 重试最多 _MAX_JSON_RETRIES 次（1s/2s 退避），
    仍失败才抛 RuntimeError，由调用方决定降级策略（同预算重试该页 / 跳过该页）。
    """
    response_format = kwargs.pop("response_format", None)
    last_err = ""
    for attempt in range(_MAX_JSON_RETRIES):
        try:
            raw = call_llm(messages, response_format=response_format, **kwargs)
            data = extract_json_block(raw)
            if data is not None:
                return data
            last_err = f"JSON 解析失败（原始回复前200字: {raw[:200]}）"
        except EmptyResponseError as e:
            last_err = str(e)
        except TruncatedResponseError:
            raise  # 截断：直接交给 _extract_one_page 走续写游标，不浪费整页重试
        except Exception as e:  # 网络抖动等
            last_err = f"调用异常: {e}"
        if attempt < _MAX_JSON_RETRIES - 1:
            time.sleep(2 ** attempt)  # 1s, 2s 指数退避
            logger.warning("call_llm_json 第 %d 次重试：%s", attempt + 1, last_err)
    raise RuntimeError(f"LLM 空响应/解析失败（已重试 {_MAX_JSON_RETRIES} 次）。{last_err}")
