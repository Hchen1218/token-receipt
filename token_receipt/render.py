"""Receipt rendering for token receipt."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
import time
from typing import List, Tuple

from .models import (
    ALLOWED_WIDTHS,
    DEFAULT_LANGUAGE,
    PriceEstimate,
    UsageSnapshot,
    canonical_language,
    center_text_visual,
    display_time,
    fmt_int,
    normalize,
    parse_iso,
    printable_receipt_char,
    truncate_visual,
    visual_char_width,
    visual_display_width,
)


LABELS = {
    "en": {
        "generic_logo": "[ AI CHECKOUT ]",
        "thanks": "THANK YOU FOR CODING WITH {product}",
        "receipt_id": "RECEIPT #: {rid}",
        "date": "DATE: {date}",
        "provider": "PROVIDER",
        "model": "MODEL",
        "context": "CONTEXT USED",
        "item": "ITEM",
        "tokens": "TOKENS",
        "input": "Input Tokens",
        "output": "Output Tokens",
        "cached": "Cache Read Tokens",
        "reasoning": "Reasoning Tokens",
        "cache_write": "Cache Write Tokens",
        "total": "TOTAL",
        "token_unit": "TOKENS",
        "estimate": "{currency} ESTIMATE",
        "price": "PRICE",
        "price_date": "PRICE DATE",
        "rate_note": "RATE NOTE",
        "unmapped": "UNMAPPED",
    },
    "zh-CN": {
        "generic_logo": "[ AI 结账 ]",
        "thanks": "感谢使用 {product}",
        "receipt_id": "小票号: {rid}",
        "date": "日期: {date}",
        "provider": "供应商",
        "model": "模型",
        "context": "已用上下文",
        "item": "项目",
        "tokens": "TOKEN",
        "input": "输入 Tokens",
        "output": "输出 Tokens",
        "cached": "缓存读取",
        "reasoning": "推理 Tokens",
        "cache_write": "缓存写入",
        "total": "总计",
        "token_unit": "Tokens",
        "estimate": "{currency} 预估",
        "price": "价格映射",
        "price_date": "价格日期",
        "rate_note": "价格说明",
        "unmapped": "未映射",
    },
}


@dataclass(frozen=True)
class ReceiptRow:
    label: str
    value: str


@dataclass(frozen=True)
class ReceiptView:
    language: str
    width: int
    logo_lines: Tuple[str, ...]
    logo_label: str
    thanks_line: str
    receipt_id_line: str
    date_line: str
    summary_rows: Tuple[ReceiptRow, ...]
    item_header: ReceiptRow
    token_rows: Tuple[ReceiptRow, ...]
    total_row: ReceiptRow
    pricing_rows: Tuple[ReceiptRow, ...]
    footer_lines: Tuple[str, ...]
    barcode_line: str
    barcode_id_line: str


class Receipt:
    def __init__(self, width: int, language: str = DEFAULT_LANGUAGE) -> None:
        if width not in ALLOWED_WIDTHS:
            raise SystemExit(f"--width must be one of {ALLOWED_WIDTHS}")
        self.width = width
        self.language = canonical_language(language)
        self.lines: List[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(truncate_visual(text, self.width, self.language))

    def center(self, text: str = "") -> None:
        self.add(center_text_visual(text, self.width, self.language))

    def rule(self, char: str = "-") -> None:
        self.add(char * self.width)

    def strong_rule(self) -> None:
        self.rule("━")

    def light_rule(self) -> None:
        self.rule("─")

    def kv(self, left: str, right: str) -> None:
        right = str(right)
        right_width = visual_display_width(right, self.language)
        max_left = max(1, int(self.width - right_width - 1))
        left = truncate_visual(left, max_left, self.language)
        left_width = visual_display_width(left, self.language)
        spaces = max(1, int(math.floor(self.width - left_width - right_width)))
        self.add(left + " " * spaces + right)

    def blank(self) -> None:
        self.add("")

    def text(self) -> str:
        for line in self.lines:
            if visual_display_width(line, self.language) > self.width + 0.51:
                raise AssertionError(f"line exceeds width: {line!r}")
            for char in line:
                if not printable_receipt_char(char):
                    raise AssertionError(f"unsupported control character: {line!r}")
        return "\n".join(self.lines)


def labels_for(language: str) -> dict[str, str]:
    return LABELS[canonical_language(language)]


def receipt_id(snapshot: UsageSnapshot, provider: str) -> str:
    stamp = parse_iso(snapshot.timestamp)
    if stamp:
        date_part = stamp.strftime("%Y%m%d_%H%M%S")
    else:
        date_part = time.strftime("%Y%m%d_%H%M%S")
    seed = f"{snapshot.session_id}:{snapshot.provider}:{snapshot.model}:{snapshot.total_tokens}:{snapshot.source}:{date_part}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6].upper()
    nk = normalize(provider)
    prefix = (
        "CC"
        if nk == "anthropic"
        else "CX"
        if nk == "openai"
        else "KM"
        if nk == "moonshot"
        else "AI"
    )
    return f"{prefix}_{date_part}_{digest}"


def barcode(seed: str, width: int) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    patterns = ["|", "||", "| ", " ||", "|||", " |"]
    raw = "".join(patterns[int(char, 16) % len(patterns)] for char in digest)
    target = min(width - 8, max(24, width - 16))
    return center_text_visual(raw[:target], width, "en")


def auto_brand(provider: str, source: str, explicit: str) -> str:
    if explicit != "auto":
        return explicit
    provider_key = normalize(provider)
    source_key = normalize(source)
    src_slash = source.replace("\\", "/").lower()
    if "#ses_" in source or source.startswith("opencode://"):
        return "opencode"
    if "/.kimi/sessions/" in src_slash or "/.kimi/imported_sessions/" in src_slash:
        return "kimi-code"
    if provider_key == "trae" or "trae" in source_key:
        return "trae"
    if provider_key == "openai" or "codex" in source_key:
        return "codex"
    if provider_key == "anthropic" or "claude" in source_key:
        return "claude-code"
    return "generic"


def add_centered_block(receipt: Receipt, lines: List[str], offset: int = 0) -> None:
    nonempty = [line for line in lines if line.strip()]
    shared_indent = min((len(line) - len(line.lstrip(" ")) for line in nonempty), default=0)
    normalized = [line[shared_indent:] for line in lines]
    block_width = max(visual_display_width(line.rstrip(), receipt.language) for line in normalized)
    left_pad = max(int(round((receipt.width - block_width) / 2)) + offset, 0)
    for line in normalized:
        receipt.add(" " * left_pad + line.rstrip())


def logo_block(agent_tool: str, language: str) -> tuple[Tuple[str, ...], str, int]:
    if agent_tool == "codex":
        return (
            (
                "      █████",
                "    █    ██   ███",
                "  ███ ██    ██   █",
                "██ ██ ██████   ███",
                "█  ██ ██    ███   █",
                "██   ███    █  ██  █",
                "  ███   █████  ██ ██",
                "  █   ██    █  ███",
                "   ███   ██    █",
                "         █████",
            ),
            "CODEX",
            0,
        )
    if agent_tool == "trae":
        return (
            (
                "   ██████████████",
                "███▒▒▒▒▒▒▒▒▒▒▒▒▒▒███",
                "███▒▒██████████▒▒███",
                "███▒▒██▒▒▒█▒▒▒█▒▒███",
                "███▒▒██████████▒▒███",
                "█████▒▒▒▒▒▒▒▒▒▒▒▒███",
                "   █████████████",
            ),
            "TRAE",
            0,
        )
    if agent_tool == "claude-code":
        return (
            (
                " ▐▛███▜▌",
                "▝▜█████▛▘",
                "  ▘▘ ▝▝",
            ),
            "CLAUDE CODE",
            -1,
        )
    if agent_tool == "kimi-code":
        return (
            (
                "       █▀▀▀▀▀▀▀█",
                "       █ ██▀ ██ █",
                "       █ ▀▀█▀▀ ██",
                "       █ █ ▄ █ ██",
                "       █ ██▄██ █▀",
                "        ▀▀▀▀▀▀▀",
            ),
            "KIMI CODE",
            0,
        )
    if agent_tool == "opencode":
        return (
            (
                "       ███████████████",
                "       █       █    ██",
                "       █ ████ ██ ████",
                "       █       █    ██",
                "       ███████████████",
            ),
            "OPENCODE",
            0,
        )
    return ((), labels_for(language)["generic_logo"], 0)


def add_logo(receipt: Receipt, agent_tool: str, language: str) -> None:
    lines, label, offset = logo_block(agent_tool, language)
    if lines:
        add_centered_block(receipt, list(lines), offset=offset)
        receipt.center(label)
        return
    receipt.center(label)


def product_name(snapshot: UsageSnapshot) -> str:
    model_key = normalize(snapshot.model)
    provider_key = normalize(snapshot.provider)
    if "claude" in model_key:
        return "Claude"
    if "codex" in model_key:
        return "Codex"
    if "gpt" in model_key:
        return "ChatGPT"
    if "gemini" in model_key or provider_key == "google":
        return "Gemini"
    if "deepseek" in model_key or provider_key == "deepseek":
        return "DeepSeek"
    if "kimi" in model_key or provider_key == "moonshot":
        return "Kimi"
    if "glm" in model_key or provider_key in ("zhipu", "bigmodel"):
        return "GLM"
    if "mimo" in model_key or provider_key == "xiaomi":
        return "MiMo"
    if "qwen" in model_key or provider_key in ("qwen", "dashscope", "alibaba"):
        return "Qwen"
    if "minimax" in model_key or provider_key == "minimax":
        return "MiniMax"
    if "trae" in model_key:
        return "Trae"
    if snapshot.model and snapshot.model != "UNRECORDED":
        return truncate_visual(snapshot.model, 16, "en")
    if provider_key == "anthropic":
        return "Claude"
    if provider_key == "openai":
        return "ChatGPT"
    return "AI"


def context_used(snapshot: UsageSnapshot) -> str:
    if snapshot.context_tokens is not None:
        used_src = snapshot.context_tokens
    else:
        used_src = snapshot.input_tokens
    used = fmt_int(used_src)
    if snapshot.context_window:
        return f"{used}/{fmt_int(snapshot.context_window)}"
    return used


def choose(options: List[str], digest: int, shift: int = 0) -> str:
    if not options:
        raise ValueError("choose() requires at least one option")
    return options[(digest >> shift) % len(options)]


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def footer_theme(snapshot: UsageSnapshot, hint: str) -> str:
    text = f"{hint} {snapshot.model} {snapshot.provider}".lower()
    visual = (
        "logo", "logos", "visual", "layout", "pixel", "pixels", "align", "alignment",
        "brand", "receipt", "poster", "icon", "视觉", "像素", "对齐", "排版", "居中", "小票", "传播",
    )
    pricing = (
        "price", "pricing", "cost", "invoice", "bill", "estimate", "usd", "cny",
        "价格", "成本", "账单", "发票", "美元", "人民币", "定价",
    )
    debug = (
        "bug", "debug", "fix", "patch", "broken", "repair", "rollback", "validate",
        "报错", "修复", "失败", "验证", "回退", "报修",
    )
    shipping = (
        "ship", "launch", "release", "deploy", "publish", "上线", "发布", "交付", "落地",
    )
    iteration = (
        "tweak", "polish", "revise", "review", "iterate", "replace",
        "打磨", "微调", "迭代", "修改", "替换", "优化",
    )
    reasoning = (
        "reason", "reasoning", "thinking", "chain", "proof", "推理", "思考", "链路", "证明",
    )
    context = (
        "context", "cache", "prompt", "memory", "上下文", "缓存", "提示词", "记忆",
    )
    if contains_any(text, visual):
        return "visual"
    if contains_any(text, pricing):
        return "pricing"
    if contains_any(text, debug):
        return "debug"
    if contains_any(text, shipping):
        return "shipping"
    if contains_any(text, iteration):
        return "iteration"
    if snapshot.reasoning_output_tokens or contains_any(text, reasoning):
        return "reasoning"
    if snapshot.cached_input_tokens or snapshot.context_window or contains_any(text, context):
        return "context"
    return "generic"


def footer_style(snapshot: UsageSnapshot, tone: str, hint: str, digest: int, language: str = DEFAULT_LANGUAGE) -> str:
    language = canonical_language(language)
    if tone in ("snarky", "encouraging", "dry"):
        return tone
    text = f"{hint} {snapshot.model} {snapshot.provider}".lower()
    warm = ("ship", "launch", "release", "publish", "上线", "发布", "交付", "落地", "完成")
    sharp = (
        "logo", "visual", "layout", "price", "pricing", "bill", "debug", "fix", "align",
        "打磨", "对齐", "价格", "账单", "修复", "验证", "回退", "替换", "迭代",
    )
    if contains_any(text, warm):
        return "encouraging"
    if language == "zh-CN":
        if contains_any(text, sharp):
            return "snarky"
        return "dry" if digest % 4 == 0 else "snarky"
    if contains_any(text, sharp):
        return "snarky"
    return "encouraging" if digest % 2 == 0 else "snarky"


def footer_topic(theme: str, hint: str, digest: int) -> str:
    text = hint.lower()
    if theme == "visual":
        if contains_any(text, ("align", "alignment", "对齐", "居中", "位置", "空隙")):
            options = ["ALIGNMENT", "LAYOUT", "PIXELS"]
        elif contains_any(text, ("logo", "icon", "brand", "header", "像素", "螃蟹")):
            options = ["LOGO", "PIXELS", "LAYOUT"]
        else:
            options = ["LAYOUT", "LOGO", "PIXELS", "ALIGNMENT"]
    elif theme == "pricing":
        options = ["PRICE TAG", "BILL", "ESTIMATE", "RECEIPT"]
    elif theme == "debug":
        options = ["FIX", "PATCH", "REGRESSION", "RECEIPT"]
    elif theme == "shipping":
        options = ["OUTPUT", "RELEASE", "BUILD", "DELIVERY"]
    elif theme == "iteration":
        options = ["TWEAK", "REVISION", "LAYOUT", "DRAFT"]
    elif theme == "reasoning":
        options = ["THINKING", "PROOF", "ANSWER", "REASONING"]
    elif theme == "context":
        options = ["CONTEXT", "CACHE", "PROMPT", "WINDOW"]
    else:
        options = ["RECEIPT", "OUTPUT", "CHAT", "DRAFT"]
    return choose(options, digest, 8)


def footer_scene(theme: str, hint: str) -> str:
    text = hint.lower()
    scene_keywords = (
        ("logo", ("logo", "icon", "brand", "header", "螃蟹", "像素", "图标")),
        ("footer", ("footer", "文案", "标语", "结尾", "收尾", "punchline")),
        ("preview", ("preview", "align", "alignment", "layout", "spacing", "居中", "对齐", "预览", "间距", "版式")),
        ("print", ("html", "print", "printer", "打印", "热敏纸", "纸张", "receipt html")),
        ("receipt", ("receipt", "bill", "invoice", "小票", "账单", "票面")),
        ("trigger", ("trigger", "hook", "sessionend", "自动触发", "触发词", "hook")),
        ("readme", ("readme", "docs", "documentation", "文档", "预览块")),
        ("pricing", ("pricing", "price", "estimate", "cost", "价格", "预估", "计价", "成本")),
    )
    for scene, words in scene_keywords:
        if contains_any(text, words):
            return scene
    if theme == "visual":
        return "preview"
    if theme == "pricing":
        return "pricing"
    if theme == "shipping":
        return "receipt"
    if theme == "debug":
        return "trigger" if contains_any(text, ("hook", "trigger", "自动触发")) else "receipt"
    return "generic"


def footer_snark_candidates(theme: str, topic: str, brand: str) -> List[str]:
    if theme == "visual":
        return [
            f"YOU SPENT TOKENS ARGUING WITH {topic}.",
            f"THE {topic} WON. THE BUDGET DID NOT.",
            f"WE USED CONTEXT TO NEGOTIATE WITH {topic}.",
            f"THE {topic} LOOKS CALM. THE BILL DOES NOT.",
            f"THIS {topic} COST MORE THAN IT LOOKS.",
        ]
    if theme == "pricing":
        return [
            f"YOU ASKED FOR A {topic}. THE TOKENS OBJECTED.",
            f"THE {topic} IS HONEST. THE PROCESS WAS NOT.",
            f"THE {topic} ARRIVED BEFORE CONSENSUS DID.",
            "THE RECEIPT IS CLEAR. THE DAMAGE IS ITEMIZED.",
            "WE COUNTED THE TOKENS. THE BILL KEPT SCORE.",
        ]
    if theme == "debug":
        return [
            "THE PATCH WORKED. THE RECEIPT KEPT SCORE.",
            "YOU BOUGHT A FIX. THE TOKENS REMEMBER.",
            "THE REGRESSION LEFT. THE BILL STAYED.",
            "THE FIX WAS CHEAPER THAN DENIAL.",
            "WE SPENT TOKENS PROVING THE FIX MATTERED.",
        ]
    if theme == "shipping":
        return [
            "IT SHIPPED. THE TOKENS WILL NEVER FORGET.",
            "THE OUTPUT IS LIVE. THE RECEIPT HAS NOTES.",
            "DELIVERY SUCCEEDED. THE BILL STAYED.",
            "THE BUILD LANDED. ACCOUNTING DID NOT SMILE.",
        ]
    if theme == "iteration":
        return [
            "ONE MORE TWEAK COST EXACTLY THIS MUCH.",
            "THE LAST REVISION WAS NOT THE LAST.",
            "WE BOUGHT POLISH BY THE TOKEN.",
            f"THIS {topic} ONLY LOOKS FINAL.",
            "THE DRAFT CHARGED AGAIN.",
        ]
    if theme == "reasoning":
        return [
            "REASONING WAS BILLED SEPARATELY.",
            "THE ANSWER WAS SHORT. THE THINKING WAS NOT.",
            "THE PROOF LOOKED CHEAP. REASONING WAS NOT.",
            "SECOND THOUGHTS WERE NOT FREE.",
            "THE ANSWER ARRIVED. THE THINKING SENT A BILL.",
        ]
    if theme == "context":
        return [
            "WE SPENT CONTEXT SO YOU COULD SAY 'ONE MORE TWEAK.'",
            "CACHE SAVED MONEY. PERFECTION DID NOT.",
            "THE CONTEXT WINDOW HELD. BARELY.",
            "YOU PAID TOKENS TO REMEMBER THIS MUCH.",
            "THE PROMPT GOT LONGER. THE PATIENCE DID NOT.",
        ]
    return [
        "THE RECEIPT IS HONEST. THE PROCESS WAS DRAMATIC.",
        "YOU BOUGHT CLARITY. THE TOKENS PAID RETAIL.",
        "THIS LOOKS EFFORTLESS. THE BILL DISAGREES.",
        "THE OUTPUT IS CLEAN. THE RECEIPT KNOWS WHY.",
        f"{brand} DID THE WORK. THE BILL WROTE NOTES.",
    ]


def footer_dry_candidates(theme: str, topic: str, brand: str) -> List[str]:
    if theme == "visual":
        return [
            "THE LOGO MOVED. THE RECEIPT RECORDED IT.",
            "ALIGNMENT CHANGED. ACCOUNTING NOTED IT.",
            "PIXELS WERE USED. THE BILL CONFIRMS IT.",
        ]
    if theme == "pricing":
        return [
            "THE ESTIMATE EXISTS. SO DOES THE OUTPUT.",
            "THE BILL IS ATTACHED TO REAL TOKENS.",
            "THE RECEIPT REMEMBERS WHAT THIS COST.",
        ]
    if theme == "debug":
        return [
            "THE FIX EXISTS. THE RECEIPT CONFIRMS IT.",
            "THE PATCH LANDED. ACCOUNTING AGREED.",
            "THE BILL NOTED THE REGRESSION.",
        ]
    if theme == "shipping":
        return [
            "DELIVERY OCCURRED. THE BILL REMAINS.",
            "THE OUTPUT SHIPPED. THE RECEIPT NOTED IT.",
        ]
    if theme == "iteration":
        return [
            "THE REVISION EXISTS. THE RECEIPT PROVES IT.",
            "THE TWEAK LANDED. THE BILL IS ATTACHED.",
        ]
    if theme == "reasoning":
        return [
            "THE THINKING USED TOKENS. THE BILL AGREES.",
            "REASONING OCCURRED. THE RECEIPT NOTED IT.",
        ]
    if theme == "context":
        return [
            "CONTEXT WAS USED. THE RECEIPT CONFIRMS IT.",
            "CACHE PARTICIPATED. ACCOUNTING APPROVED.",
        ]
    return [
        "THE TOKENS WERE USED. THE RECEIPT CONFIRMS IT.",
        "THIS OUTPUT HAS A BILL.",
        f"{brand} FINISHED. THE RECEIPT LOGGED IT.",
    ]


def footer_encouraging_candidates(theme: str, topic: str, brand: str) -> List[str]:
    if theme == "visual":
        return [
            "THE PIXELS ARE QUIET NOW. KEEP GOING.",
            "THE LAYOUT FINALLY BREATHES. GOOD CALL.",
            "YOU SPENT TOKENS. THE SCREENSHOT GOT BETTER.",
            "THE LOGO SETTLED DOWN. SO DID THE RECEIPT.",
        ]
    if theme == "pricing":
        return [
            "THE BILL IS HONEST. SO IS THE RESULT.",
            "YOU PAID FOR CLARITY. THAT PART MATTERS.",
            "THE ESTIMATE IS CLEAR. THE WORK IS REAL.",
            "THE PRICE TAG IS CLEAN. KEEP BUILDING.",
        ]
    if theme == "debug":
        return [
            "THE FIX COST TOKENS. THE CALM WAS INCLUDED.",
            "YOU PAID FOR A FIX. YOU KEPT THE MOMENTUM.",
            "THE PATCH HELD. SO DID THE DIRECTION.",
        ]
    if theme == "shipping":
        return [
            "THE OUTPUT LANDED. KEEP THE MOMENTUM.",
            "DELIVERY COST TOKENS. THE RESULT MOVED.",
        ]
    if theme == "iteration":
        return [
            "THE TWEAK COST TOKENS. THE TASTE IMPROVED.",
            "THE REVISION LANDED. THE RECEIPT LOOKS LIGHTER.",
        ]
    if theme == "reasoning":
        return [
            "THE THINKING TOOK TOKENS. THE ANSWER EARNED THEM.",
            "THE PROOF COST SOMETHING. IT WAS WORTH IT.",
            "REASONING TOOK ITS TIME. CLARITY STAYED.",
        ]
    if theme == "context":
        return [
            "THE CONTEXT HELD. SO DID THE IDEA.",
            "CACHE SAVED TIME. YOU KEPT THE DIRECTION.",
            "THE WINDOW WAS TIGHT. THE RESULT STILL FIT.",
        ]
    return [
        "THE TOKENS LEFT. THE MOMENTUM STAYED.",
        "YOU SPENT CONTEXT. THE RESULT KEPT THE CHANGE.",
        "THIS COST TOKENS. IT ALSO MOVED.",
        f"{brand} KEPT GOING. SO DID YOU.",
    ]


def footer_bill_state(snapshot: UsageSnapshot, estimate: PriceEstimate) -> str:
    if snapshot.reasoning_output_tokens and snapshot.reasoning_output_tokens >= max(64, snapshot.output_tokens // 3):
        return "reasoning_heavy"
    if snapshot.input_tokens and snapshot.cached_input_tokens >= max(1, snapshot.input_tokens // 2):
        return "cache_heavy"
    amount = float(estimate.amount or 0.0)
    if amount >= 0.5:
        return "heavy"
    if amount >= 0.1:
        return "medium"
    return "light"


def tip_state(percent: float | int | None) -> str:
    value = float(percent or 0.0)
    if value <= 0:
        return "none"
    if value >= 25:
        return "lavish"
    if value >= 20:
        return "generous"
    if value >= 18:
        return "standard"
    return "polite"


def en_tip_subject(scene: str, brand: str) -> str:
    if scene == "logo":
        return "THE LOGO"
    if scene == "footer":
        return "THE SIGN-OFF"
    if scene == "preview":
        return "THE PREVIEW"
    if scene == "print":
        return "THE PRINT VIEW"
    if scene == "receipt":
        return "THE RECEIPT"
    if scene == "trigger":
        return "THE TRIGGER"
    if scene == "readme":
        return "THE README"
    if scene == "pricing":
        return "THE PRICE TAG"
    return brand


def zh_tip_subject(scene: str, brand: str) -> str:
    if scene == "logo":
        return "Logo"
    if scene == "footer":
        return "收尾"
    if scene == "preview":
        return "预览"
    if scene == "print":
        return "打印效果"
    if scene == "receipt":
        return "这张小票"
    if scene == "trigger":
        return "触发逻辑"
    if scene == "readme":
        return "README"
    if scene == "pricing":
        return "价格这部分"
    return "这一版"


def en_tip_footer_candidates(scene: str, style: str, bill_state: str, current_tip_state: str, brand: str) -> List[str]:
    _ = scene
    _ = brand
    if current_tip_state == "polite":
        if style == "snarky":
            lines = [
                "FINALLY SETTLED. THAT TIP WAS SMALL BUT CORRECT.",
                "HELD TOGETHER. THE REGISTER CALLS THAT POLITE.",
                "LANDED CLEAN. SMALL KINDNESS NOTED.",
            ]
        elif style == "dry":
            lines = [
                "IN PLACE NOW. A POLITE GRATUITY WAS RECORDED.",
                "STABLE ENOUGH. SMALL SUPPORT WAS APPLIED.",
                "READY TO GO. THE TIP ENTRY WAS ACCEPTED.",
            ]
        else:
            lines = [
                "IN A BETTER PLACE NOW. THANKS FOR THE EXTRA NOD.",
                "SETTLED DOWN. THAT LITTLE BIT OF KINDNESS HELPED.",
                "LOOKING RIGHT NOW. POLITE SUPPORT RECEIVED.",
            ]
    elif current_tip_state == "standard":
        if style == "snarky":
            lines = [
                "FINALLY LANDED. STANDARD KINDNESS ACCEPTED.",
                "LOOKS RIGHT NOW. THE COUNTER APPROVES.",
                "STOPPED ARGUING. GRATUITY NOTED WITHOUT DRAMA.",
            ]
        elif style == "dry":
            lines = [
                "NOW STABLE. STANDARD GRATUITY APPLIED.",
                "SETTLED AT LAST. STANDARD TIP RECORDED.",
                "READY FOR CHECKOUT. THE EXTRA WAS APPROVED.",
            ]
        else:
            lines = [
                "FINALLY FEELS COMPLETE. THANKS, THAT WAS THE RIGHT KIND OF GENEROUS.",
                "LOOKS BETTER NOW. SOLID GRATUITY. GOOD FORM.",
                "HELD UP WELL. STANDARD KINDNESS LANDED.",
            ]
    elif current_tip_state == "generous":
        if style == "snarky":
            lines = [
                "LOOKS EXPENSIVE IN THE RIGHT WAY. GENEROSITY DETECTED.",
                "FINALLY BEHAVED. THE REGISTER FELT THAT ONE.",
                "CAME TOGETHER. THIS TIP HAD OPINIONS.",
            ]
        elif style == "dry":
            lines = [
                "NOW SETTLED. GENEROSITY RECORDED.",
                "IN GOOD SHAPE. HIGH GRATUITY APPLIED.",
                "READY FOR PRINT. THE EXTRA WAS NOTED.",
            ]
        else:
            lines = [
                "LOOKS GOOD NOW. THANKS, THE CLERK FEELS SEEN.",
                "FINALLY LANDED. THIS WAS GENEROUS IN A USEFUL WAY.",
                "IN PLACE NOW. THE EXTRA LANDED WELL.",
            ]
    else:
        if style == "snarky":
            lines = [
                "LOCKED IN. THIS WAS LESS A TIP THAN A POSITION.",
                "FINALLY HAS ITS SHAPE. THE REGISTER GOT THE MESSAGE.",
                "LANDED HARD. THAT GRATUITY MADE THE POINT CLEAR.",
            ]
        elif style == "dry":
            lines = [
                "NOW FINAL. A LARGE GRATUITY WAS APPLIED.",
                "COMPLETE AT LAST. LAVISH SUPPORT WAS RECORDED.",
                "READY TO CLOSE. THE EXTRA EXCEEDED NORMAL CHECKOUT.",
            ]
        else:
            lines = [
                "FEELS COMPLETE NOW. THANKS, THAT WAS OPENLY KIND.",
                "FINALLY LOOKS RIGHT. THIS RECEIPT WILL REMEMBER YOU FONDLY.",
                "LANDED WELL. THE COUNTER APPRECIATES THE COMMITMENT.",
            ]

    if bill_state == "heavy":
        lines.append("TOOK A REAL BILL TO GET HERE. THE EXTRA STILL LOOKS DELIBERATE.")
    elif bill_state == "reasoning_heavy":
        lines.append("COST A FAIR BIT OF THINKING. THE GRATUITY STILL LANDED CLEAN.")
    elif bill_state == "cache_heavy":
        lines.append("CACHE DID SOME OF THE LIFTING. THE EXTRA STILL COUNTS.")
    return lines


def zh_tip_footer_candidates(
    scene: str,
    style: str,
    bill_state: str,
    current_tip_state: str,
    brand: str,
    digest: int,
) -> List[str]:
    base: dict[str, dict[str, List[str]]] = {
        "footer": {
            "polite": [
                "现在收得挺顺，您这点心意它领得起。",
                "尾巴总算收圆了，这一笔，收银台先替它道谢。",
                "这回落笔挺漂亮，小费不大，排面给足了。",
            ],
            "standard": [
                "这回收得很体面，您这笔像专门来抬轿。",
                "末尾终于有劲了，收银台替它领了这份好意。",
                "这一收，连标点都跟着有了底气。",
            ],
            "generous": [
                "收得真像样了，您这一笔把气氛都养贵了。",
                "这回末尾有排面了，收银台都替它把腰弯下去了。",
                "一句落稳，整张票都像被您请客了。",
            ],
            "lavish": [
                "这回收得像压轴，您这不是给小费，是给它抬身价。",
                "末尾现在有脸见人了，收银台差点替它起立。",
                "这一收，连账单都被您哄得会笑了。",
            ],
        },
        "print": {
            "polite": [
                "这回终于能落纸了，您这点心意连打印机都哄好了。",
                "纸面终于不闹了，这一笔刚好够它收敛脾气。",
                "这张纸总算肯配合了，收银台替它先说声谢谢。",
            ],
            "standard": [
                "打印终于不翻车了，您这笔像在给纸面赔了个笑脸。",
                "这回终于能直接出纸了，这份体面给得很会挑时候。",
                "纸面终于服帖了，收银台看得出您是真心想哄好它。",
            ],
            "generous": [
                "打印终于像样了，您这一笔给得，纸都不好意思卡了。",
                "这张纸总算争气了，收银台已经替它低头致谢了。",
                "终于能直接拿去打印了，这份小费把场面养得很体面。",
            ],
            "lavish": [
                "纸面终于活过来了，您这一下给得像在给它续命。",
                "打印终于不丢人了，这笔一上来，连卡纸都得讲礼貌。",
                "这张纸终于肯站队了，收银台已经想替它鞠个躬。",
            ],
        },
        "preview": {
            "polite": [
                "预览终于不别扭了，您这点心意刚好把它哄顺了。",
                "这一版总算站住了，这笔不大，排面倒是补上了。",
                "版面终于顺下来了，收银台替眼睛先领这份情。",
            ],
            "standard": [
                "版面终于顺眼了，您这笔像在给审美发补贴。",
                "预览终于安静了，这份体面来得很会做人。",
                "这一版终于立住了，收银台看得出您是来哄场面的。",
            ],
            "generous": [
                "这版终于能看了，您这笔一到，像素都开始懂事了。",
                "预览终于收声了，这份小费把脾气养得很温顺。",
                "版面终于站稳了，收银台已经替它学会说谢谢了。",
            ],
            "lavish": [
                "这一屏终于服帖了，您这已经不是小费，是宠爱。",
                "预览终于闭嘴了，这一笔下去，连焦虑都得改口叫您老板。",
                "这版终于彻底站住了，收银台都快替它喊声恩人了。",
            ],
        },
        "logo": {
            "polite": [
                "Logo 终于站正了，您这点心意把它哄得很服帖。",
                "抬头总算安分了，这一笔不大，脸面倒是有了。",
                "这块图标终于不闹了，收银台替它先谢谢您。",
            ],
            "standard": [
                "Logo 终于对齐了，您这笔像在给它发调教奖金。",
                "抬头终于不斜了，这份体面给得像老手。",
                "这块标终于站住了，收银台看得出您是真想把它宠好。",
            ],
            "generous": [
                "Logo 终于能见人了，您这笔给得像是专门替它撑场。",
                "抬头终于服帖了，这份小费一下就把脾气养软了。",
                "这块图标终于稳了，收银台已经替它把腰弯下去了。",
            ],
            "lavish": [
                "Logo 终于像样了，您这一笔下去，它都快以为自己是主角了。",
                "抬头终于立住了，这份出手已经够它记一辈子。",
                "这块图标终于争气了，收银台现在只想替它谢谢老板。",
            ],
        },
        "receipt": {
            "polite": [
                "这张票终于像真账单了，您这点心意把它抬得很体面。",
                "这张票总算能见人了，这笔刚好给它补足了脸色。",
                "这张票终于立住了，收银台替它先领这份情。",
            ],
            "standard": [
                "这张票终于像回事了，您这笔像在给账单发体面费。",
                "这张票终于顺眼了，这份小费来得很会挑时候。",
                "这张票终于收住了，收银台看得出您是来给它撑腰的。",
            ],
            "generous": [
                "这张票终于拿得出手了，您这笔给得像替它补了排面。",
                "这张票终于立住了，这份小费一下就让它有了底气。",
                "这张票终于像在认真结账了，收银台替它把谢谢都说重了。",
            ],
            "lavish": [
                "这张票终于像张真凭据了，您这已经不是给小费，是给它长脸。",
                "这张票终于彻底站住了，这一笔下去，它都快想叫您贵人。",
                "这张票终于争气了，收银台替它把感激写进抬头里了。",
            ],
        },
        "readme": {
            "polite": [
                "这一页终于能放出来了，您这点心意把它衬得更体面了。",
                "这版 README 总算顺了，这一笔刚好够它把腰挺直。",
                "这块说明终于不别扭了，收银台替它先把谢意领了。",
            ],
            "standard": [
                "这一页终于能见人了，您这笔像在给文案发体面补贴。",
                "README 终于顺眼了，这份小费把场面哄得很服帖。",
                "这块说明终于立住了，收银台看得出您是真宠它。",
            ],
            "generous": [
                "这一页终于像样了，您这笔给得像在替它撑场面。",
                "README 终于服帖了，这份小费把脾气一下养软了。",
                "这块说明终于能打了，收银台都想替它道谢三次。",
            ],
            "lavish": [
                "这一页终于站稳了，您这已经不是给小费，是给体面续命。",
                "README 总算争气了，这一笔下去，它都快学会鞠躬了。",
                "这块说明终于能拿去见人了，收银台替它记下这份恩情了。",
            ],
        },
        "pricing": {
            "polite": [
                "这次终于像在认真结账了，您这点心意把心虚都压下去了。",
                "数字终于站住了，这一笔不大，排面倒是给足了。",
                "这一栏总算不抖了，收银台替它先谢谢您。",
            ],
            "standard": [
                "这回终于像真收银台了，您这笔像在给账单发奖金。",
                "数字终于说人话了，这份体面来得很会挑时候。",
                "这一栏终于稳住了，收银台认这份会来事。",
            ],
            "generous": [
                "这次终于真像在买单了，您这笔给得比数字还痛快。",
                "数字终于不飘了，这份小费一下把脸色养好了。",
                "这一栏终于能看了，收银台都想替它喊声老板大气。",
            ],
            "lavish": [
                "这次终于像在当场买单了，您这已经不是小费，是排面。",
                "数字终于服帖了，这一笔下去，连账单都像被哄好了。",
                "这一栏终于有了收银台的脸，收银台已经替它改口叫贵客了。",
            ],
        },
        "trigger": {
            "polite": [
                "这回触发终于顺了，您这点心意刚好把逻辑哄住。",
                "这次总算不用跟触发较劲了，这一笔来得很会做人。",
                "这套逻辑终于不拧巴了，收银台替它先领这份情。",
            ],
            "standard": [
                "这回触发终于对上了，您这笔像在给流程发奖金。",
                "这次终于不用反复试了，这份体面把场面哄得很顺。",
                "这套逻辑终于顺下来了，收银台认这份会来事。",
            ],
            "generous": [
                "这回触发终于稳了，您这笔给得像在替它撑腰。",
                "这次终于能一次过了，这份小费把脾气养得很软。",
                "这套逻辑终于不拧了，收银台都快替它鞠躬了。",
            ],
            "lavish": [
                "这回触发终于彻底服帖了，您这已经不是小费，是宠爱。",
                "这次终于不用再追着试了，这一笔下去，连逻辑都学会感恩了。",
                "这套逻辑终于争气了，收银台替它把谢意写满了全页。",
            ],
        },
        "generic": {
            "polite": [
                "这一版终于顺下来了，您这点心意刚好把它哄顺了。",
                "这回总算像样了，这一笔不大，脸面倒是补上了。",
                "这轮终于能落地了，收银台先替它谢谢您。",
            ],
            "standard": [
                "这一版终于站住了，您这笔像在给结果发体面费。",
                "这回总算对味了，这份小费把场面哄得很顺。",
                "这轮终于收住了，收银台认这份会来事。",
            ],
            "generous": [
                "这一版终于能见人了，您这笔给得像在替它撑场面。",
                "这回总算顺透了，这份小费把脾气都养软了。",
                "这轮终于落住了，收银台已经替它把感谢说重了。",
            ],
            "lavish": [
                "这一版终于彻底站住了，您这已经不是小费，是偏爱。",
                "这回总算争气了，这一笔下去，连账单都想改口叫您老板。",
                "这轮终于有了样子，收银台替它把感激写进眉眼里了。",
            ],
        },
    }

    scene_key = scene if scene in base else "generic"
    subject = zh_tip_subject(scene_key, brand)
    lines = list(base[scene_key][current_tip_state])

    style_overrides: dict[str, dict[str, List[str]]] = {
        "snarky": {
            "polite": [
                "钱不算多，姿态已经给够了。",
                "这一点意思不重，场面倒是顾全了。",
            ],
            "standard": [
                "这笔给得挺懂规矩，收银台记住了。",
                "这份体面不算夸张，刚好够它改口。",
            ],
            "generous": [
                "这一笔一下去，账单都学会看人下菜了。",
                "钱给得挺会挑时候，收银台立刻学乖了。",
            ],
            "lavish": [
                "这已经不是加一点，是顺手把它供起来了。",
                "这一笔给得太明白，收银台都知道该站哪边了。",
            ],
        },
        "dry": {
            "polite": [
                "意思到了，单据知道。",
                "金额不大，谢意成立。",
            ],
            "standard": [
                "体面已到账，票面确认。",
                "这笔额外费用，已被收银台记录。",
            ],
            "generous": [
                "额外金额已记录，口气随之放软。",
                "出手明显，票面确认。",
            ],
            "lavish": [
                "大额谢意已记录，场面随之改变。",
                "这一笔超出礼数，收银台确认。",
            ],
        },
        "encouraging": {
            "polite": [
                f"{subject}已经顺下来了，这点心意来得正好。",
                "这一下不重，但足够让场面好看。",
            ],
            "standard": [
                f"{subject}已经站住了，这份体面给得刚刚好。",
                "这一笔落得很稳，连语气都跟着变好了。",
            ],
            "generous": [
                f"{subject}现在挺有样子，您这笔确实会抬场。",
                "这一笔一到，整张票都像被顺手提了一下气色。",
            ],
            "lavish": [
                f"{subject}现在是真有面子了，您这一下给得很够意思。",
                "这笔一上来，整张票都像有人替它撑腰了。",
            ],
        },
    }

    bill_overrides: dict[str, dict[str, List[str]]] = {
        "heavy": {
            "polite": [
                "单子本来就不轻，您这点意思反而更显眼。",
            ],
            "standard": [
                "账单已经不算客气了，您这笔倒还给了台阶。",
            ],
            "generous": [
                "这单子本来就挺敢开，您还顺手把场面补圆了。",
            ],
            "lavish": [
                "账单都开成这样了，您这一笔还是给得像在罩着它。",
            ],
        },
        "reasoning_heavy": {
            "polite": [
                "这轮想得不少，您这点意思倒也来得很识趣。",
            ],
            "standard": [
                "推理费已经说够话了，您这笔又替它补了语气。",
            ],
            "generous": [
                "这轮脑力税不轻，您这一下倒像在替它善后。",
            ],
            "lavish": [
                "它已经把思考费写在脸上了，您这笔还照样给得很大方。",
            ],
        },
        "cache_heavy": {
            "polite": [
                "缓存帮它省了点脸，您这点意思还是另算的。",
            ],
            "standard": [
                "缓存替它挡了一半，您这笔还是照样算体面。",
            ],
            "generous": [
                "缓存都替它省着花了，您这一笔反倒更像偏爱。",
            ],
            "lavish": [
                "它都知道拿缓存省钱了，您这一笔还是给得像在宠着它。",
            ],
        },
    }

    style_lines = style_overrides.get(style, style_overrides["snarky"])[current_tip_state]
    bill_lines = bill_overrides.get(bill_state, {}).get(current_tip_state, [])

    if style == "snarky":
        candidates = style_lines + lines + bill_lines
    elif style == "dry":
        candidates = lines[:1] + style_lines + lines[1:] + bill_lines
    else:
        candidates = lines + style_lines + bill_lines

    deduped: List[str] = []
    seen: set[str] = set()
    rotate = digest % max(len(candidates), 1)
    ordered = candidates[rotate:] + candidates[:rotate]
    for line in ordered:
        if line in seen:
            continue
        deduped.append(line)
        seen.add(line)
    return deduped


def auto_tip_footer(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    tone: str,
    width: int,
    language: str,
    hint: str = "",
    tip_percent: float | int = 0,
) -> str:
    return fit_footer_text(
        auto_tip_footer_line(snapshot, estimate, tone, language, hint, tip_percent),
        width,
        language,
    )


def auto_tip_footer_line(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    tone: str,
    language: str,
    hint: str = "",
    tip_percent: float | int = 0,
) -> str:
    language = canonical_language(language)
    current_tip_state = tip_state(tip_percent)
    if current_tip_state == "none":
        return auto_footer_line(snapshot, estimate, tone, language, hint)

    key = (
        f"tip:{language}:{snapshot.provider}:{snapshot.model}:{snapshot.total_tokens}:"
        f"{snapshot.cached_input_tokens}:{snapshot.reasoning_output_tokens}:{hint}:{tone}:"
        f"{estimate.status}:{estimate.amount}:{tip_percent}"
    )
    digest = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)
    theme = footer_theme(snapshot, hint)
    scene = footer_scene(theme, hint)
    style = footer_style(snapshot, tone, hint, digest, language)
    bill_state = footer_bill_state(snapshot, estimate)
    brand = product_name(snapshot).upper()

    if language == "zh-CN":
        return choose(zh_tip_footer_candidates(scene, style, bill_state, current_tip_state, brand, digest), digest, 18)

    return choose(en_tip_footer_candidates(scene, style, bill_state, current_tip_state, brand), digest, 18)


def zh_footer_snark_candidates(theme: str) -> List[str]:
    if theme == "visual":
        return [
            "画面稳了，预算死了。",
            "像素满意了，钱包没有。",
            "你修的是对齐，坏的是预算。",
            "这一版更顺眼，也更伤钱。",
        ]
    if theme == "pricing":
        return [
            "价格很透明，破防也很透明。",
            "数字很清楚，心情更清楚。",
            "报价到了，侥幸死了。",
            "账单没情绪，你有。",
        ]
    if theme == "debug":
        return [
            "问题死了，账单活着。",
            "Bug 修完了，费用继承了。",
            "补丁合上了，钱包裂开了。",
            "错误消失了，代价留档了。",
        ]
    if theme == "shipping":
        return [
            "东西发出去了，钱回不来了。",
            "上线了，预算没了。",
            "交付完成，余款阵亡。",
        ]
    if theme == "iteration":
        return [
            "最后一版这个词，本来就不诚实。",
            "再改一版，先死一笔。",
            "你改的是细节，账单改的是态度。",
            "版本更好了，现金流更坏了。",
        ]
    if theme == "reasoning":
        return [
            "推理不免费，犹豫更贵。",
            "答案出来了，脑力税也出来了。",
            "思考得很认真，结账也很认真。",
            "结论落地了，推理费追上来了。",
        ]
    if theme == "context":
        return [
            "上下文撑住了，预算先躺下了。",
            "模型记住了很多，钱包也记住了。",
            "缓存救了一点，不够救你。",
            "窗口没爆，余额先爆了。",
        ]
    return [
        "结果很体面，账单更诚实。",
        "看起来很轻松，付起来不是。",
        "结果拿到了，嘴硬资格没了。",
        "事做完了，单也做出来了。",
    ]


def zh_footer_dry_candidates(theme: str) -> List[str]:
    if theme == "visual":
        return [
            "Logo 动了，账单留档。",
            "对齐改了，费用也在。",
            "像素没白用，钱也没白花。",
        ]
    if theme == "pricing":
        return [
            "价格在这里，幻想不在。",
            "账单跟着 token 一起落地。",
            "这次花费，票面记得很清楚。",
        ]
    if theme == "debug":
        return [
            "修复落地了，费用也落地了。",
            "补丁合上了，账单跟上了。",
            "问题过去了，账单没有。",
        ]
    if theme == "shipping":
        return [
            "交付完成了，票面还在。",
            "结果发出去了，账单留着。",
        ]
    if theme == "iteration":
        return [
            "这一版存在，账单作证。",
            "调整完成，费用附上。",
        ]
    if theme == "reasoning":
        return [
            "思考发生了，账单记下了。",
            "推理出现了，费用也出现了。",
        ]
    if theme == "context":
        return [
            "上下文用掉了，票面确认。",
            "缓存参与了，账单也参与了。",
        ]
    return [
        "Token 用掉了，账单确认。",
        "这次输出，有账单。",
        "事情做完了，费用也做完了。",
    ]


def zh_footer_encouraging_candidates(theme: str) -> List[str]:
    if theme == "visual":
        return [
            "像素终于安静了，继续。",
            "排版顺了，图能发了。",
            "钱花了，截图也能用了。",
            "Logo 稳住了，小票也能见人了。",
        ]
    if theme == "pricing":
        return [
            "账单是诚实的，结果也是。",
            "你花的是明白钱。",
            "价格清楚，活也清楚。",
            "这笔费用，至少换来了结果。",
        ]
    if theme == "debug":
        return [
            "修复花了 token，但方向保住了。",
            "这次扣费，换来了清净。",
            "补丁落地了，节奏没断。",
        ]
    if theme == "shipping":
        return [
            "结果落地了，继续推进。",
            "钱花在交付上，不算白花。",
        ]
    if theme == "iteration":
        return [
            "这次微调花了钱，但确实更好了。",
            "这一版落地了，至少不是白改。",
        ]
    if theme == "reasoning":
        return [
            "思考花了 token，答案值回来了。",
            "推理费不低，结论还在。",
            "结论不是免费的，但它到了。",
        ]
    if theme == "context":
        return [
            "上下文撑住了，想法也撑住了。",
            "缓存省了点时间，方向没丢。",
            "窗口很紧，结果还是塞进去了。",
        ]
    return [
        "这笔钱，至少换来了结果。",
        "结果出来了，账单也认了。",
        "钱烧掉了，事情推进了。",
        "小票出来了，这轮不算白跑。",
    ]


def split_display_text(text: str, max_width: int, language: str) -> tuple[str, str]:
    left: list[str] = []
    width = 0.0
    index = 0
    for index, char in enumerate(text):
        char_width = visual_char_width(char, language)
        if width + char_width > max_width:
            break
        left.append(char)
        width += char_width
    else:
        return text, ""
    return "".join(left).rstrip(), text[index:].lstrip()


def fit_footer_text(text: str, width: int, language: str) -> str:
    language = canonical_language(language)
    max_line = min(width, 40)
    normalized = re.sub(r"\s+", " ", text.strip())
    if visual_display_width(normalized, language) <= max_line:
        return normalized

    words = normalized.split()
    if len(words) > 1:
        for split_at in range(len(words) - 1, 0, -1):
            left = " ".join(words[:split_at])
            right = " ".join(words[split_at:])
            if visual_display_width(left, language) <= max_line and visual_display_width(right, language) <= max_line:
                return left + "\n" + right

    left, right = split_display_text(normalized, max_line, language)
    if not right:
        return left
    return left + "\n" + truncate_visual(right, max_line, language)


def auto_footer_line(snapshot: UsageSnapshot, estimate: PriceEstimate, tone: str, language: str, hint: str = "") -> str:
    language = canonical_language(language)
    key = f"{language}:{snapshot.provider}:{snapshot.model}:{snapshot.total_tokens}:{snapshot.cached_input_tokens}:{snapshot.reasoning_output_tokens}:{hint}:{tone}:{estimate.status}"
    digest = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)
    theme = footer_theme(snapshot, hint)
    style = footer_style(snapshot, tone, hint, digest, language)
    brand = product_name(snapshot).upper()
    if language == "zh-CN":
        if style == "snarky":
            candidates = zh_footer_snark_candidates(theme)
        elif style == "dry":
            candidates = zh_footer_dry_candidates(theme)
        else:
            candidates = zh_footer_encouraging_candidates(theme)
        return choose(candidates, digest, 14)

    topic = footer_topic(theme, hint, digest)
    if style == "snarky":
        candidates = footer_snark_candidates(theme, topic, brand)
    elif style == "dry":
        candidates = footer_dry_candidates(theme, topic, brand)
    else:
        candidates = footer_encouraging_candidates(theme, topic, brand)
    return choose(candidates, digest, 14)


def auto_footer(snapshot: UsageSnapshot, estimate: PriceEstimate, tone: str, width: int, language: str, hint: str = "") -> str:
    return fit_footer_text(auto_footer_line(snapshot, estimate, tone, language, hint), width, language)


def footer_lines(text: str, width: int, language: str) -> List[str]:
    language = canonical_language(language)
    normalized = text.replace("\\n", "\n")
    lines: List[str] = []
    for raw in normalized.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if language == "en":
            raw = raw.upper()
        lines.append(truncate_visual(raw, width, language))
    return lines or [""]


def source_has(snapshot: UsageSnapshot, field: str) -> bool:
    return field in snapshot.available_fields


def currency_symbol(currency: str) -> str:
    key = currency.upper()
    if key == "USD":
        return "$"
    if key in ("CNY", "RMB"):
        return "¥"
    return f"{key} "


def money(amount: float | None, currency: str = "USD") -> str:
    if amount is None:
        return "UNMAPPED"
    if 0 < amount < 0.000001:
        return f"<{currency_symbol(currency)}0.000001"
    return f"{currency_symbol(currency)}{amount:.6f}"


def build_receipt_view(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    width: int,
    agent_tool: str,
    footer: str,
    footer_tone: str,
    conversation_hint: str,
    language: str = DEFAULT_LANGUAGE,
    hidden: frozenset = frozenset(),
) -> ReceiptView:
    language = canonical_language(language)
    labels = labels_for(language)
    provider = snapshot.provider.upper() if snapshot.provider else "UNKNOWN"
    rid = receipt_id(snapshot, snapshot.provider)
    footer_text = auto_footer(snapshot, estimate, footer_tone, width, language, conversation_hint) if footer == "auto" else footer

    summary_rows = (
        ReceiptRow(labels["provider"], provider),
        ReceiptRow(labels["model"], snapshot.model),
        ReceiptRow(labels["context"], context_used(snapshot)),
    )
    token_rows: list[ReceiptRow] = []
    if source_has(snapshot, "input_tokens"):
        token_rows.append(ReceiptRow(labels["input"], fmt_int(snapshot.input_tokens)))
    if source_has(snapshot, "output_tokens"):
        token_rows.append(ReceiptRow(labels["output"], fmt_int(snapshot.output_tokens)))
    if source_has(snapshot, "cached_input_tokens"):
        token_rows.append(ReceiptRow(labels["cached"], fmt_int(snapshot.cached_input_tokens)))
    if source_has(snapshot, "reasoning_output_tokens"):
        token_rows.append(ReceiptRow(labels["reasoning"], fmt_int(snapshot.reasoning_output_tokens)))
    if source_has(snapshot, "cache_write_tokens"):
        token_rows.append(ReceiptRow(labels["cache_write"], fmt_int(snapshot.cache_write_tokens)))

    pricing_rows = [
        ReceiptRow(labels["estimate"].format(currency=estimate.currency), money(estimate.amount, estimate.currency)),
        ReceiptRow(labels["price"], labels["unmapped"] if estimate.status == "UNMAPPED" else estimate.model),
    ]
    if estimate.status != "UNMAPPED":
        if estimate.source_checked_at and "price-date" not in hidden:
            pricing_rows.append(ReceiptRow(labels["price_date"], estimate.source_checked_at))
        if estimate.rate_note and "rate-note" not in hidden:
            pricing_rows.append(ReceiptRow(labels["rate_note"], estimate.rate_note))

    logo_lines, logo_label, _ = logo_block(agent_tool, language)
    return ReceiptView(
        language=language,
        width=width,
        logo_lines=logo_lines,
        logo_label=logo_label,
        thanks_line=labels["thanks"].format(product=product_name(snapshot)),
        receipt_id_line=labels["receipt_id"].format(rid=rid),
        date_line=labels["date"].format(date=display_time(snapshot.timestamp)),
        summary_rows=summary_rows,
        item_header=ReceiptRow(labels["item"], labels["tokens"]),
        token_rows=tuple(token_rows),
        total_row=ReceiptRow(labels["total"], f"{fmt_int(snapshot.total_tokens)} {labels['token_unit']}"),
        pricing_rows=tuple(pricing_rows),
        footer_lines=tuple(footer_lines(footer_text, width, language)),
        barcode_line=barcode(rid, width),
        barcode_id_line=rid,
    )


def render_receipt(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    width: int,
    agent_tool: str,
    footer: str,
    footer_tone: str,
    conversation_hint: str,
    language: str = DEFAULT_LANGUAGE,
    hidden: frozenset = frozenset(),
) -> str:
    view = build_receipt_view(snapshot, estimate, width, agent_tool, footer, footer_tone, conversation_hint, language, hidden=hidden)
    receipt = Receipt(width, view.language)

    add_logo(receipt, agent_tool, view.language)
    receipt.blank()
    receipt.center(view.thanks_line)
    receipt.center(view.receipt_id_line)
    receipt.center(view.date_line)
    receipt.strong_rule()
    for row in view.summary_rows:
        receipt.kv(row.label, row.value)
    receipt.light_rule()
    receipt.kv(view.item_header.label, view.item_header.value)
    receipt.light_rule()
    for row in view.token_rows:
        receipt.kv(row.label, row.value)
    receipt.strong_rule()
    receipt.kv(view.total_row.label, view.total_row.value)
    receipt.light_rule()
    for row in view.pricing_rows:
        receipt.kv(row.label, row.value)
    receipt.strong_rule()
    for line in view.footer_lines:
        receipt.center(line)
    receipt.blank()
    receipt.add(view.barcode_line)
    receipt.center(view.barcode_id_line)
    return receipt.text()


def print_receipt(text: str, stream: bool, delay: float) -> None:
    if not stream:
        print(text)
        return
    for line in text.splitlines():
        print(line, flush=True)
        if delay > 0:
            time.sleep(delay)
