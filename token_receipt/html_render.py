"""Printable HTML rendering for token receipt."""

from __future__ import annotations

from base64 import b64encode
from functools import lru_cache
from html import escape
import json
from pathlib import Path

from .models import DEFAULT_LANGUAGE, PriceEstimate, SKILL_DIR, UsageSnapshot, canonical_language
from .render import ReceiptRow, auto_footer_line, auto_tip_footer_line, build_receipt_view, money


def _render_rows(rows: tuple[ReceiptRow, ...]) -> str:
    return "\n".join(
        f'        <div class="receipt-row"><span class="receipt-label">{escape(row.label)}</span><span class="receipt-value">{escape(row.value)}</span></div>'
        for row in rows
    )


HTML_LOGO_ASSETS = {
    "codex": SKILL_DIR / "token_receipt" / "assets" / "codex-logo.png",
    "trae": SKILL_DIR / "token_receipt" / "assets" / "trae-logo.png",
}

HTML_LANGUAGES = ("en", "zh-CN")
TIP_PRESETS = (15, 18, 20, 25)
TIP_UI_LABELS = {
    "en": {
        "toggle": "Add tip",
        "subtotal": "SUBTOTAL",
        "tip": "TIP",
        "grand_total": "GRAND TOTAL",
        "language_button": "EN",
    },
    "zh-CN": {
        "toggle": "加一点小费",
        "subtotal": "小计",
        "tip": "小费",
        "grand_total": "应付总额",
        "language_button": "中文",
    },
}


CLAUDE_CODE_SVG = """
<svg class="receipt-logo-svg receipt-logo-svg--claude-code" viewBox="0 0 128 76" aria-hidden="true" focusable="false">
  <g fill="currentColor" shape-rendering="crispEdges">
    <rect x="22" y="4" width="84" height="22" />
    <rect x="10" y="30" width="108" height="14" />
    <rect x="24" y="44" width="80" height="14" />
    <rect x="30" y="60" width="8" height="12" />
    <rect x="48" y="60" width="8" height="12" />
    <rect x="78" y="60" width="8" height="12" />
    <rect x="96" y="60" width="8" height="12" />
  </g>
  <g fill="#ffffff" shape-rendering="crispEdges">
    <rect x="38" y="12" width="10" height="14" />
    <rect x="80" y="12" width="10" height="14" />
  </g>
</svg>
""".strip()


def _normalize_footer_for_html(text: str, language: str) -> str:
    parts = [part.strip() for part in text.replace("\\n", "\n").splitlines() if part.strip()]
    if not parts:
        return ""
    if canonical_language(language) == "zh-CN":
        return "".join(parts)
    return " ".join(parts).upper()


def _json_script_payload(data: object) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


@lru_cache(maxsize=None)
def _asset_data_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/svg+xml" if suffix == ".svg" else None
    if mime is None:
        return None
    return f"data:{mime};base64,{b64encode(path.read_bytes()).decode('ascii')}"


def _logo_markup(agent_tool: str, logo_lines: tuple[str, ...]) -> str:
    if agent_tool == "claude-code":
        return f'          <div class="receipt-logo-shell">{CLAUDE_CODE_SVG}</div>\n'
    asset = HTML_LOGO_ASSETS.get(agent_tool)
    if asset:
        data_uri = _asset_data_uri(asset)
        if data_uri:
            return (
                '          <div class="receipt-logo-shell">'
                f'<img class="receipt-logo-image receipt-logo-image--{escape(agent_tool)}" src="{data_uri}" alt="" aria-hidden="true" />'
                "</div>\n"
            )
    if not logo_lines:
        return ""
    return (
        '          <div class="receipt-logo-shell">\n'
        '            <pre class="receipt-logo" aria-hidden="true">'
        + escape("\n".join(logo_lines))
        + "</pre>\n"
        "          </div>\n"
    )


def _tip_config(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    footer_tone: str,
    width: int,
    language: str,
    conversation_hint: str,
    default_footer_text: str,
) -> dict[str, object] | None:
    if estimate.status != "ESTIMATE" or estimate.amount is None:
        return None
    labels = TIP_UI_LABELS[canonical_language(language)]
    options: list[dict[str, object]] = []
    for percent in TIP_PRESETS:
        tip_amount = estimate.amount * (percent / 100.0)
        grand_total = estimate.amount + tip_amount
        options.append(
            {
                "percent": percent,
                "tipAmount": money(tip_amount, estimate.currency),
                "grandTotal": money(grand_total, estimate.currency),
                "footer": _normalize_footer_for_html(
                    auto_tip_footer_line(
                        snapshot,
                        estimate,
                        footer_tone,
                        language,
                        conversation_hint,
                        tip_percent=percent,
                    )
                , language),
            }
        )
    return {
        "language": canonical_language(language),
        "defaultFooter": default_footer_text,
        "subtotal": money(estimate.amount, estimate.currency),
        "subtotalLabel": labels["subtotal"],
        "tipLabel": labels["tip"],
        "grandTotalLabel": labels["grand_total"],
        "options": options,
    }


def _tip_summary_markup(labels: dict[str, str], subtotal: str) -> str:
    return (
        '        <section class="receipt-tip-summary" hidden>\n'
        '          <div class="receipt-rule"></div>\n'
        '          <div class="receipt-row">'
        f'<span class="receipt-label">{escape(labels["subtotal"])}</span>'
        f'<span class="receipt-value" data-tip-subtotal>{escape(subtotal)}</span>'
        "</div>\n"
        '          <div class="receipt-row">'
        f'<span class="receipt-label" data-tip-line-label>{escape(labels["tip"])} (0%)</span>'
        '<span class="receipt-value" data-tip-amount></span>'
        "</div>\n"
        '          <div class="receipt-row receipt-total">'
        f'<span class="receipt-label">{escape(labels["grand_total"])}</span>'
        '<span class="receipt-value" data-tip-grand-total></span>'
        "</div>\n"
        "        </section>\n"
    )


def _render_receipt_article(
    view,
    agent_tool: str,
    footer_text: str,
    tip_summary_markup: str,
    active: bool,
) -> str:
    logo_art = _logo_markup(agent_tool, view.logo_lines)
    hidden_class = "" if active else " receipt--hidden"
    return (
        f'      <article class="receipt{hidden_class}" data-language="{escape(view.language)}">\n'
        '        <header class="receipt-header">\n'
        f"{logo_art}"
        f'          <div class="receipt-logo-label">{escape(view.logo_label)}</div>\n'
        f'          <div class="receipt-thanks">{escape(view.thanks_line)}</div>\n'
        f'          <div class="receipt-meta">{escape(view.receipt_id_line)}</div>\n'
        f'          <div class="receipt-meta">{escape(view.date_line)}</div>\n'
        "        </header>\n"
        '        <div class="receipt-rule strong"></div>\n'
        f"{_render_rows(view.summary_rows)}\n"
        '        <div class="receipt-rule"></div>\n'
        f"{_render_rows((view.item_header,))}\n"
        '        <div class="receipt-rule"></div>\n'
        f"{_render_rows(view.token_rows)}\n"
        '        <div class="receipt-rule strong"></div>\n'
        '        <div class="receipt-total">\n'
        f"{_render_rows((view.total_row,))}\n"
        "        </div>\n"
        '        <div class="receipt-rule"></div>\n'
        f"{_render_rows(view.pricing_rows)}\n"
        f"{tip_summary_markup}"
        '        <footer class="receipt-footer">\n'
        '          <div class="receipt-rule strong"></div>\n'
        f'          <div class="receipt-footer-line" data-receipt-footer>{escape(footer_text)}</div>\n'
        f'          <pre class="receipt-barcode" aria-hidden="true">{escape(view.barcode_line.strip())}</pre>\n'
        f'          <div class="receipt-barcode-id">{escape(view.barcode_id_line)}</div>\n'
        "        </footer>\n"
        "      </article>\n"
    )


def render_receipt_html(
    snapshot: UsageSnapshot,
    estimate: PriceEstimate,
    width: int,
    agent_tool: str,
    footer: str,
    footer_tone: str,
    conversation_hint: str,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    page_lang = canonical_language(language)
    views = {
        lang: build_receipt_view(snapshot, estimate, width, agent_tool, footer, footer_tone, conversation_hint, lang)
        for lang in HTML_LANGUAGES
    }
    active_view = views[page_lang]
    title = escape(active_view.barcode_id_line)
    tip_labels = TIP_UI_LABELS[page_lang]
    footer_texts = {}
    for lang in HTML_LANGUAGES:
        raw_footer = (
            auto_footer_line(snapshot, estimate, footer_tone, lang, conversation_hint)
            if footer == "auto"
            else footer
        )
        footer_texts[lang] = _normalize_footer_for_html(raw_footer, lang)
    tip_configs = {
        lang: _tip_config(snapshot, estimate, footer_tone, width, lang, conversation_hint, footer_texts[lang])
        for lang in HTML_LANGUAGES
    }
    config_payload = {
        "defaultLanguage": page_lang,
        "uiLabels": TIP_UI_LABELS,
        "tip": tip_configs,
    }
    language_buttons = "\n".join(
        f'          <button class="language-option{" is-selected" if lang == page_lang else ""}" type="button" data-language-button="{lang}" aria-pressed="{"true" if lang == page_lang else "false"}">{escape(TIP_UI_LABELS[lang]["language_button"])}</button>'
        for lang in HTML_LANGUAGES
    )
    language_panel = (
        '      <section class="receipt-language-panel">\n'
        '        <div class="receipt-language-controls">\n'
        f"{language_buttons}\n"
        "        </div>\n"
        "      </section>\n"
    )
    tip_panel = ""
    tip_script = ""
    if tip_configs[page_lang] is not None:
        option_buttons = "\n".join(
            f'            <button class="tip-option" type="button" data-tip-percent="{percent}">{percent}%</button>'
            for percent in TIP_PRESETS
        )
        tip_panel = (
            '      <section class="receipt-tip-panel">\n'
            '        <section class="receipt-tip-controls">\n'
            '          <label class="tip-toggle">\n'
            '            <input id="tip-toggle" type="checkbox" />\n'
            f'            <span id="tip-toggle-label">{escape(tip_labels["toggle"])}</span>\n'
            '          </label>\n'
            '          <div class="tip-options" id="tip-options" hidden>\n'
            f"{option_buttons}\n"
            "          </div>\n"
            "        </section>\n"
            "      </section>\n"
        )
        tip_script = (
            f'    <script id="tip-config" type="application/json">{_json_script_payload(config_payload)}</script>\n'
            "    <script>\n"
            "      (() => {\n"
            "        const node = document.getElementById('tip-config');\n"
            "        if (!node) return;\n"
            "        const config = JSON.parse(node.textContent || '{}');\n"
            "        let activeLanguage = config.defaultLanguage || 'en';\n"
            "        const toggle = document.getElementById('tip-toggle');\n"
            "        const optionsWrap = document.getElementById('tip-options');\n"
            "        const buttons = Array.from(document.querySelectorAll('[data-tip-percent]'));\n"
            "        const languageButtons = Array.from(document.querySelectorAll('[data-language-button]'));\n"
            "        const receipts = Array.from(document.querySelectorAll('.receipt[data-language]'));\n"
            "        const tipToggleLabel = document.getElementById('tip-toggle-label');\n"
            "        let selectedPercent = null;\n"
            "        const tipConfigFor = (lang) => (config.tip || {})[lang] || null;\n"
            "        const receiptFor = (lang) => document.querySelector(`.receipt[data-language=\"${lang}\"]`);\n"
            "        const optionMapFor = (lang) => new Map(((tipConfigFor(lang) || {}).options || []).map((item) => [String(item.percent), item]));\n"
            "        const resetReceipt = (lang) => {\n"
            "          const receipt = receiptFor(lang);\n"
            "          const tipConfig = tipConfigFor(lang);\n"
            "          if (!receipt || !tipConfig) return;\n"
            "          const summary = receipt.querySelector('.receipt-tip-summary');\n"
            "          const footer = receipt.querySelector('[data-receipt-footer]');\n"
            "          const lineLabel = receipt.querySelector('[data-tip-line-label]');\n"
            "          const tipAmount = receipt.querySelector('[data-tip-amount]');\n"
            "          const grandTotal = receipt.querySelector('[data-tip-grand-total]');\n"
            "          if (footer) footer.textContent = tipConfig.defaultFooter || '';\n"
            "          if (summary) summary.hidden = true;\n"
            "          if (tipAmount) tipAmount.textContent = '';\n"
            "          if (grandTotal) grandTotal.textContent = '';\n"
            "          if (lineLabel) lineLabel.textContent = `${tipConfig.tipLabel} (0%)`;\n"
            "        };\n"
            "        const applySelectionToReceipt = (lang, percent) => {\n"
            "          const receipt = receiptFor(lang);\n"
            "          const tipConfig = tipConfigFor(lang);\n"
            "          if (!receipt || !tipConfig) return;\n"
            "          const optionMap = optionMapFor(lang);\n"
            "          const option = optionMap.get(String(percent));\n"
            "          if (!option) return;\n"
            "          const summary = receipt.querySelector('.receipt-tip-summary');\n"
            "          const footer = receipt.querySelector('[data-receipt-footer]');\n"
            "          const lineLabel = receipt.querySelector('[data-tip-line-label]');\n"
            "          const tipAmount = receipt.querySelector('[data-tip-amount]');\n"
            "          const grandTotal = receipt.querySelector('[data-tip-grand-total]');\n"
            "          if (summary) summary.hidden = false;\n"
            "          if (lineLabel) lineLabel.textContent = `${tipConfig.tipLabel} (${option.percent}%)`;\n"
            "          if (tipAmount) tipAmount.textContent = option.tipAmount;\n"
            "          if (grandTotal) grandTotal.textContent = option.grandTotal;\n"
            "          if (footer) footer.textContent = option.footer;\n"
            "        };\n"
            "        const syncVisibleState = () => {\n"
            "          receipts.forEach((receipt) => {\n"
            "            const lang = receipt.dataset.language;\n"
            "            if (!lang) return;\n"
            "            if (toggle && toggle.checked && selectedPercent) {\n"
            "              applySelectionToReceipt(lang, selectedPercent);\n"
            "            } else {\n"
            "              resetReceipt(lang);\n"
            "            }\n"
            "          });\n"
            "        };\n"
            "        const applyLanguage = (lang) => {\n"
            "          activeLanguage = lang;\n"
            "          document.documentElement.lang = lang;\n"
            "          receipts.forEach((receipt) => {\n"
            "            const active = receipt.dataset.language === lang;\n"
            "            receipt.classList.toggle('receipt--hidden', !active);\n"
            "          });\n"
            "          languageButtons.forEach((button) => {\n"
            "            const active = button.dataset.languageButton === lang;\n"
            "            button.classList.toggle('is-selected', active);\n"
            "            button.setAttribute('aria-pressed', active ? 'true' : 'false');\n"
            "          });\n"
            "          if (tipToggleLabel && config.uiLabels && config.uiLabels[lang]) {\n"
            "            tipToggleLabel.textContent = config.uiLabels[lang].toggle;\n"
            "          }\n"
            "        };\n"
            "        buttons.forEach((button) => {\n"
            "          button.setAttribute('aria-pressed', 'false');\n"
            "          button.addEventListener('click', () => {\n"
            "            selectedPercent = button.dataset.tipPercent;\n"
            "            buttons.forEach((candidate) => {\n"
            "              const active = candidate.dataset.tipPercent === selectedPercent;\n"
            "              candidate.classList.toggle('is-selected', active);\n"
            "              candidate.setAttribute('aria-pressed', active ? 'true' : 'false');\n"
            "            });\n"
            "            syncVisibleState();\n"
            "          });\n"
            "        });\n"
            "        languageButtons.forEach((button) => {\n"
            "          button.addEventListener('click', () => applyLanguage(button.dataset.languageButton));\n"
            "        });\n"
            "        if (toggle) {\n"
            "          toggle.addEventListener('change', () => {\n"
            "            const enabled = !!toggle.checked;\n"
            "            if (optionsWrap) optionsWrap.hidden = !enabled;\n"
            "            if (!enabled) {\n"
            "              selectedPercent = null;\n"
            "              buttons.forEach((candidate) => {\n"
            "                candidate.classList.remove('is-selected');\n"
            "                candidate.setAttribute('aria-pressed', 'false');\n"
            "              });\n"
            "            }\n"
            "            syncVisibleState();\n"
            "          });\n"
            "        }\n"
            "        applyLanguage(activeLanguage);\n"
            "        syncVisibleState();\n"
            "      })();\n"
            "    </script>\n"
        )
    receipt_articles = "".join(
        _render_receipt_article(
            view,
            agent_tool,
            footer_texts[lang],
            _tip_summary_markup(TIP_UI_LABELS[lang], str(tip_configs[lang]["subtotal"])) if tip_configs[lang] is not None else "",
            active=(lang == page_lang),
        )
        for lang, view in views.items()
    )
    return f"""<!DOCTYPE html>
<html lang="{escape(page_lang)}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title} · token-receipt</title>
    <style>
      :root {{
        color-scheme: light;
        --page-bg: #ececec;
        --paper: #ffffff;
        --ink: #151515;
        --rule: #232323;
        --receipt-width: 80mm;
        --pad-x: 4mm;
        --pad-top: 7mm;
        --pad-bottom: 4.8mm;
        --logo-width: 24mm;
        --logo-shell-height: 26mm;
        --logo-label-size: 4.3mm;
        --meta-size: 3.2mm;
        --row-size: 3.45mm;
        --footer-size: 3.55mm;
        --barcode-size: 3.15mm;
        --barcode-id-size: 3.15mm;
      }}
      * {{
        box-sizing: border-box;
      }}
      html, body {{
        margin: 0;
        padding: 0;
        background: var(--page-bg);
        color: var(--ink);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      }}
      body {{
        min-height: 100vh;
        padding: 12px 0 24px;
      }}
      .print-toolbar {{
        display: flex;
        justify-content: center;
        margin-bottom: 12px;
      }}
      .print-button {{
        appearance: none;
        border: 0;
        border-radius: 999px;
        padding: 10px 18px;
        background: #1b1c1f;
        color: #fff;
        font: inherit;
        cursor: pointer;
      }}
      .print-button:hover {{
        background: #33363d;
      }}
      .receipt-page {{
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 20px 0 28px;
        background: var(--page-bg);
        gap: 10px;
      }}
      .receipt {{
        width: min(var(--receipt-width), calc(100vw - 24px));
        background: var(--paper);
        padding: var(--pad-top) var(--pad-x) var(--pad-bottom);
        position: relative;
        overflow: hidden;
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.04);
      }}
      .receipt--hidden {{
        display: none;
      }}
      .receipt-header,
      .receipt-footer {{
        text-align: center;
      }}
      .receipt-logo-shell {{
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: var(--logo-shell-height);
      }}
      .receipt-logo {{
        display: block;
        margin: 0;
        white-space: pre;
        line-height: 1.02;
        font-size: 4.25mm;
      }}
      .receipt-logo-image {{
        display: block;
        width: var(--logo-width);
        height: auto;
        image-rendering: pixelated;
      }}
      .receipt-logo-svg {{
        display: block;
        width: var(--logo-width);
        height: auto;
        color: var(--ink);
      }}
      .receipt-logo-svg--claude-code {{
        width: calc(var(--logo-width) - 0.8mm);
        transform: translateX(-0.45mm);
      }}
      .receipt-logo-image--codex,
      .receipt-logo-image--trae {{
        width: var(--logo-width);
        max-height: var(--logo-shell-height);
      }}
      .receipt-logo-label {{
        margin-top: 3mm;
        font-size: var(--logo-label-size);
        letter-spacing: 0.08em;
      }}
      .receipt-thanks,
      .receipt-meta {{
        margin-top: 2.7mm;
        font-size: var(--meta-size);
        line-height: 1.35;
      }}
      .receipt-meta {{
        margin-top: 0.9mm;
      }}
      .receipt-rule {{
        border-top: 0.35mm solid var(--rule);
        margin: 3.5mm 0;
      }}
      .receipt-rule.strong {{
        border-top-width: 0.55mm;
      }}
      .receipt-tip-panel {{
        width: min(var(--receipt-width), calc(100vw - 24px));
        display: flex;
        justify-content: center;
      }}
      .receipt-language-panel {{
        width: min(var(--receipt-width), calc(100vw - 24px));
        display: flex;
        justify-content: center;
      }}
      .receipt-language-controls {{
        width: 100%;
        display: flex;
        justify-content: center;
        gap: 1.5mm;
        padding: 3mm 4mm;
        background: rgba(255, 255, 255, 0.55);
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.05);
      }}
      .language-option {{
        appearance: none;
        border: 0.25mm solid var(--rule);
        background: var(--paper);
        color: var(--ink);
        font: inherit;
        font-size: 3mm;
        line-height: 1;
        padding: 1.8mm 3.2mm;
        cursor: pointer;
      }}
      .language-option.is-selected {{
        background: var(--ink);
        color: var(--paper);
      }}
      .receipt-tip-controls {{
        width: 100%;
        padding: 3.5mm 4mm;
        text-align: center;
        background: rgba(255, 255, 255, 0.55);
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.05);
      }}
      .receipt-tip-controls,
      .receipt-tip-controls * {{
        user-select: none;
      }}
      .receipt-tip-summary {{
        margin-top: 2.8mm;
      }}
      .tip-toggle {{
        display: inline-flex;
        align-items: center;
        gap: 2mm;
        font-size: var(--meta-size);
        cursor: pointer;
      }}
      .tip-toggle input {{
        width: 4mm;
        height: 4mm;
        margin: 0;
      }}
      .tip-options {{
        display: flex;
        justify-content: center;
        flex-wrap: wrap;
        gap: 1.5mm;
        margin-top: 2mm;
      }}
      .tip-options[hidden],
      .receipt-tip-summary[hidden] {{
        display: none !important;
      }}
      .tip-option {{
        appearance: none;
        border: 0.25mm solid var(--rule);
        background: var(--paper);
        color: var(--ink);
        font: inherit;
        font-size: 3mm;
        line-height: 1;
        padding: 1.8mm 2.6mm;
        cursor: pointer;
      }}
      .tip-option.is-selected {{
        background: var(--ink);
        color: var(--paper);
      }}
      .receipt-row {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 4mm;
        align-items: baseline;
        font-size: var(--row-size);
        line-height: 1.32;
      }}
      .receipt-label {{
        padding-right: 2mm;
        min-width: 0;
      }}
      .receipt-value {{
        text-align: right;
        white-space: nowrap;
      }}
      .receipt-total {{
        font-size: calc(var(--row-size) + 0.15mm);
      }}
      .receipt-footer {{
        margin-top: 3.2mm;
        padding: 0 0.6mm;
      }}
      .receipt-footer-line {{
        font-size: var(--footer-size);
        line-height: 1.35;
        white-space: normal;
        overflow-wrap: break-word;
        text-wrap: balance;
      }}
      .receipt-barcode {{
        margin: 3.6mm 0 1.4mm;
        white-space: pre;
        font-size: var(--barcode-size);
        line-height: 1;
        overflow: hidden;
      }}
      .receipt-barcode-id {{
        font-size: var(--barcode-id-size);
        line-height: 1.25;
        word-break: break-all;
      }}
      @page {{
        size: 80mm auto;
        margin: 0;
      }}
      @media print {{
        body {{
          background: #fff;
          padding: 0;
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }}
        .print-toolbar,
        .receipt-note,
        .receipt-language-panel,
        .receipt-tip-panel,
        .receipt-tip-controls {{
          display: none;
        }}
        .receipt-page {{
          display: block;
          padding: 0;
          background: transparent;
        }}
        .receipt {{
          width: var(--receipt-width);
          margin: 0 auto;
          box-shadow: none;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="print-toolbar">
      <button class="print-button" type="button" onclick="window.print()">Print receipt</button>
    </div>
    <main class="receipt-page">
{receipt_articles}
{language_panel}
{tip_panel}
    </main>
{tip_script}
  </body>
</html>
"""
