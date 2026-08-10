import re
import secrets

EASYTURN_LABEL_RE = re.compile(r"<(\w+)>")
PAUSE_ANNOTATION_THRESHOLD_SECONDS = 0.5
PAUSE_ANNOTATION_THRESHOLD_MS = int(PAUSE_ANNOTATION_THRESHOLD_SECONDS * 1000)


def is_annotatable_pause(duration: object) -> bool:
    """Return whether a pause is long enough to be treated as a pause."""
    try:
        return float(duration) >= PAUSE_ANNOTATION_THRESHOLD_SECONDS
    except (TypeError, ValueError):
        return False


def is_annotatable_pause_ms(duration_ms: object) -> bool:
    """Millisecond form of the pause threshold for legacy payloads."""
    try:
        return float(duration_ms) >= PAUSE_ANNOTATION_THRESHOLD_MS
    except (TypeError, ValueError):
        return False


def remove_short_pause_tags(text: str) -> str:
    """Remove pause markers below the annotation threshold from display text."""
    pattern = re.compile(r"<PAUSE:(\d+(?:\.\d+)?)s>")

    def replace(match: re.Match[str]) -> str:
        return match.group(0) if is_annotatable_pause(match.group(1)) else ""

    return pattern.sub(replace, text or "")


def remove_last_annotatable_pause_tag(text: str) -> str:
    """Remove only the final pause marker that meets the pause threshold."""
    pattern = re.compile(r"<PAUSE:(\d+(?:\.\d+)?)s>")
    matches = [
        match for match in pattern.finditer(text or "")
        if is_annotatable_pause(match.group(1))
    ]
    if not matches:
        return text or ""
    match = matches[-1]
    return (text or "")[:match.start()] + (text or "")[match.end():]


def extract_annotatable_pause_items(text: str) -> list[dict]:
    """Extract the remaining eligible pause markers from display text."""
    pattern = re.compile(r"<PAUSE:(\d+(?:\.\d+)?)s>")
    items = []
    for match in pattern.finditer(text or ""):
        duration = float(match.group(1))
        if not is_annotatable_pause(duration):
            continue
        items.append({
            "duration": duration,
            "kind": "pause",
            "position": match.start(),
        })
    return items


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def parse_easyturn(raw: str) -> tuple[str, str | None]:
    """
    输入："因为小时候<incomplete><|endoftext|>"
    返回：(clean_text, label)  如 ("因为小时候", "incomplete")
    """
    clean = re.sub(r"<\|endoftext\|>", "", raw, flags=re.IGNORECASE).strip()
    match = EASYTURN_LABEL_RE.findall(clean)
    label = match[-1].lower() if match else None
    if label:
        clean = re.sub(rf"\s*<{re.escape(label)}>\s*$", "", clean).strip()
    return clean, label


# 默认配置——与 models/settings 保持一致，也用于首次初始化
LEGACY_DEFAULT_INSTRUCTION = """任务说明
下面呈现的是你刚才与主试完成英语口语任务时的对话转录。系统已在你的部分发言处标出可能与「未说完 / 需要等待」相关的位置。

请你做什么
请依次查看每一处标记。结合前后对话，回忆当时你为什么会这样停顿、犹豫或没有继续说完，并填写：
1）最符合的原因类别；
2）当时的原因与心理过程（请写具体一些，例如你在想哪个词、哪句结构、还是在组织内容）；
3）你对上述描述的确信程度（1–7）。

描述建议
- 请尽量描述「当下」的想法，而不是事后合理化。
- 建议每处约 20–100 字；若确实记不清，可如实写"记不清"，并在置信度上选择较低分数。
- 主试的发言仅帮助你回忆语境，无需对主试发言作答。

提交
所有标记处填写完成后，点击顶部「提交」。提交后不可再修改。填写过程中会自动保存进度，可中途关闭，稍后用同一链接继续。"""

DEFAULT_INSTRUCTION = """任务说明
下面呈现的是你刚才与主试完成英语口语任务时的对话转录。系统已在你的部分发言处标出你发言时“停顿”的位置。

请你做什么
请依次查看每一处标记。结合前后对话，回忆当时你为什么会这样停顿、犹豫或没有继续说完，并填写：
1）最符合的原因类别；
2）当时的原因与心理过程（请写具体一些，例如你在想哪个词、哪句结构、还是在组织内容）；
3）你对上述描述的确信程度（1–7）。

描述建议
- 请尽量描述「当下」的想法，而不是事后合理化。
- 建议每处约 20–100 字；若确实记不清，可如实写"记不清"，并在置信度上选择较低分数。
- 主试的发言仅帮助你回忆语境，无需对主试发言作答。

提交
所有标记处填写完成后，点击顶部「提交」。提交后不可再修改。填写过程中会自动保存进度，可中途关闭，稍后用同一链接继续。"""

DEFAULT_ANNOTATABLE_LABELS = ["incomplete", "wait"]

DEFAULT_REASON_CATEGORIES = [
    {"value": "memory_retrieval", "label": "记忆检索（从记忆中提取过去的经历、事实或其他相关信息）"},
    {"value": "content_planning", "label": "内容规划（规划接下来要表达的内容、信息顺序及具体展开方式）"},
    {"value": "lexical_retrieval", "label": "词汇检索（检索或选择表达当前意思所需的某个单词或词组）"},
    {"value": "sentence_organization", "label": "句式组织（选择或重新组织表达当前意思的句式，包括比较不同表达方案、安排词序及确定分句关系）"},
    {"value": "phonological_encoding", "label": "语音编码（准备或确认即将说出的词语的发音形式及语音实现方式）"},
    {"value": "emphatic_pause", "label": "强调性停顿（通过停顿突出后续内容的重要性、对比关系或转折）"},
    {"value": "other", "label": "其他"},
]

LEGACY_DEFAULT_REASON_CATEGORY_VALUES = (
    "lexical", "syntax", "thinking", "intention_shift", "interactive", "external", "other"
)


def is_legacy_default_reason_categories(categories: object) -> bool:
    """Identify the original built-in list so existing settings can be upgraded."""
    if not isinstance(categories, list):
        return False
    values = [item.get("value") for item in categories if isinstance(item, dict)]
    return values == list(LEGACY_DEFAULT_REASON_CATEGORY_VALUES)

LABEL_HINTS = {
    "incomplete": "未说完",
    "wait": "等待",
    "complete": "完整",
    "backchannel": "附和",
}
