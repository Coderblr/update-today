"""Java Page Object parser.

Extracts Selenium locators from Java PO files (`private final By txtAcctNo =
By.id("...")`) and produces rows in the same dict schema as `locator_file_parsers.py`
so they can be ingested directly into the Locator Repository.

Handles: By.id, By.xpath, By.cssSelector, By.name, By.className, By.linkText,
By.partialLinkText.
"""

import re

# ── Abbreviation expansion ────────────────────────────────────────────────────
_ABBREV = {
    "acct": "Account", "amt": "Amount", "no": "Number", "num": "Number",
    "txn": "Transaction", "dt": "Date", "ref": "Reference", "narr": "Narration",
    "sts": "Status", "bal": "Balance", "cust": "Customer", "dep": "Deposit",
    "wd": "Withdrawal", "cd": "Cash Drawer", "frm": "From", "rsn": "Reason",
    "pwd": "Password", "id": "ID",
}

# ── Variable-name prefix → control_type ──────────────────────────────────────
_PREFIX_CONTROL = {
    "txt": "text_input", "btn": "button", "rbtn": "radio", "cbtn": "checkbox",
    "chk": "checkbox", "drp": "select", "sel": "select", "lbl": "text_input",
    "alrt": "text_input", "lnk": "text_input", "img": "text_input",
    "tbl": "text_input", "div": "text_input",
}
_MANDATORY_PREFIXES = {"txt"}
_SORTED_PREFIXES = sorted(_PREFIX_CONTROL, key=len, reverse=True)

# Matches `private final By varName = By.strategy("value");`
_FIELD_RE = re.compile(
    r"(?:private|protected|public)?\s*(?:final\s+)?By\s+(\w+)\s*=\s*(By\.\w+\s*\(.*?\))\s*;",
    re.DOTALL,
)
_BY_RE = re.compile(
    r"By\.(id|xpath|cssSelector|name|className|tagName|linkText|partialLinkText)"
    r'\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)',
    re.DOTALL,
)


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def _split_camel(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", s)
    parts = []
    for w in s.split():
        expanded = _ABBREV.get(w.lower())
        if expanded is None:
            parts.append(w.capitalize())
        elif expanded:
            parts.append(expanded)
    return " ".join(parts).strip()


def _infer(var_name: str) -> tuple[str, str]:
    """Returns (field_name, prefix)."""
    for p in _SORTED_PREFIXES:
        if var_name.lower().startswith(p) and var_name[len(p):]:
            return _split_camel(var_name[len(p):]), p
    return _split_camel(var_name), ""


def _parse_by(by_expr: str) -> dict | None:
    m = _BY_RE.search(by_expr)
    if not m:
        return None
    strategy, raw = m.group(1), _unescape(m.group(2))
    if strategy == "id":
        return {
            "priority_locator": f"#{raw}",
            "priority_locator_type": "css",
            "fallback_locator": f"//*[@id='{raw}']",
            "fallback_locator_type": "xpath",
        }
    if strategy in ("cssSelector", "className", "tagName"):
        css = raw if strategy == "cssSelector" else f".{raw}" if strategy == "className" else raw
        return {"priority_locator": css, "priority_locator_type": "css",
                "fallback_locator": None, "fallback_locator_type": None}
    if strategy == "xpath":
        return {"priority_locator": raw, "priority_locator_type": "xpath",
                "fallback_locator": None, "fallback_locator_type": None}
    if strategy == "name":
        return {"priority_locator": f"//*[@name='{raw}']", "priority_locator_type": "xpath",
                "fallback_locator": f"[name='{raw}']", "fallback_locator_type": "css"}
    if strategy in ("linkText", "partialLinkText"):
        xpath = f"//a[normalize-space()='{raw}']" if strategy == "linkText" else f"//a[contains(.,'{raw}')]"
        return {"priority_locator": xpath, "priority_locator_type": "xpath",
                "fallback_locator": None, "fallback_locator_type": None}
    return None


def parse_java_po(
    source: str,
    transaction_number: str,
    screen_name: str,
    confidence: float = 0.95,
) -> list[dict]:
    """Parse Java PO source and return rows compatible with locator_file_parsers schema."""
    rows = []
    seen = set()
    for m in _FIELD_RE.finditer(source):
        var_name, by_expr = m.group(1), m.group(2)
        if var_name in seen:
            continue
        seen.add(var_name)
        locator = _parse_by(by_expr)
        if locator is None:
            continue
        field_name, prefix = _infer(var_name)
        rows.append({
            "transaction_number": transaction_number,
            "screen_name": screen_name,
            "field_name": field_name,
            "priority_locator": locator["priority_locator"],
            "priority_locator_type": locator.get("priority_locator_type", "css"),
            "fallback_locator": locator.get("fallback_locator"),
            "fallback_locator_type": locator.get("fallback_locator_type"),
            "ai_confidence_score": confidence,
            "is_mandatory": prefix in _MANDATORY_PREFIXES,
            "control_type": _PREFIX_CONTROL.get(prefix, "text_input"),
        })
    return rows
