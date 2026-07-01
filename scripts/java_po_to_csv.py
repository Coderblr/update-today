"""
Convert Java Selenium Page Object files to NBC Platform locator CSV.

Usage:
    python scripts/java_po_to_csv.py <JavaPOFile.java> --txn 001060 --screen "Cash Withdrawal"

Output:
    A .csv file (same name, .csv extension) ready to upload via the Locator Management
    Dashboard (/locators/manage → Upload).

Handles:
    By.id(...)          → CSS  #id  (fallback: XPath //*[@id='...'])
    By.cssSelector(...) → CSS  as-is
    By.xpath(...)       → XPath as-is
    By.name(...)        → XPath //*[@name='...']
    By.className(...)   → CSS .class
    By.linkText(...)    → stored as XPath //a[normalize-space()='...']

Field names are inferred from the Java variable name by stripping common prefixes
(txt, btn, rbtn, chk, drp, lbl, alrt, lnk) and splitting camelCase into words.
Pass --interactive to review and rename each field name before writing the CSV.
"""

import argparse
import csv
import sys
from pathlib import Path

# Import the shared parser from the backend package so logic is never duplicated.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.java_po_parser import parse_java_po  # noqa: E402

# ── Common banking abbreviation expansions applied to inferred field names ────
# Applied word-by-word after camelCase splitting so "AcctNo" → "Account Number".
_ABBREV_EXPAND = {
    "acct": "Account",
    "amt":  "Amount",
    "no":   "Number",
    "num":  "Number",
    "txn":  "Transaction",
    "dt":   "Date",
    "ref":  "Reference",
    "narr": "Narration",
    "sts":  "Status",
    "bal":  "Balance",
    "cust": "Customer",
    "dep":  "Deposit",
    "wd":   "Withdrawal",
    "cd":   "Cash Drawer",
    "frm":  "From",
    "rsn":  "Reason",
    "pwd":  "Password",
    "id":   "ID",
    "btn":  "",   # shouldn't appear after prefix strip, but belt-and-suspenders
}

# ── Prefix → control_type mapping ────────────────────────────────────────────
_PREFIX_CONTROL = {
    "txt":   "text_input",
    "btn":   "button",
    "rbtn":  "radio",
    "cbtn":  "checkbox",
    "chk":   "checkbox",
    "drp":   "select",
    "sel":   "select",
    "lbl":   "text_input",
    "alrt":  "text_input",
    "lnk":   "text_input",
    "img":   "text_input",
    "tbl":   "text_input",
    "div":   "text_input",
}
# Text inputs are treated as potentially mandatory; everything else defaults to not.
_MANDATORY_PREFIXES = {"txt"}

# Longer prefixes must be checked first so "rbtn" beats "btn".
_SORTED_PREFIXES = sorted(_PREFIX_CONTROL.keys(), key=len, reverse=True)


def _split_camel(name: str) -> str:
    """'accntNumber' → 'Account Number'  (handles consecutive caps like 'XMLParser')."""
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    spaced = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", spaced)
    words = spaced.split()
    # Expand common banking abbreviations word-by-word
    expanded = []
    for w in words:
        expansion = _ABBREV_EXPAND.get(w.lower())
        if expansion is None:
            expanded.append(w.capitalize())
        elif expansion:
            expanded.append(expansion)
        # empty expansion = drop the word (e.g. a stray "btn")
    return " ".join(expanded).strip()


def _infer_field_name(var_name: str) -> tuple[str, str]:
    """Returns (field_name, prefix)."""
    for prefix in _SORTED_PREFIXES:
        if var_name.lower().startswith(prefix):
            remainder = var_name[len(prefix):]
            if remainder:
                return _split_camel(remainder), prefix
    return _split_camel(var_name), ""


def _parse_by(by_expr: str) -> dict | None:
    """
    Parse a single By.<strategy>("...") expression.
    Returns a dict with keys: priority_locator, priority_locator_type,
    fallback_locator, fallback_locator_type — or None if unparseable.
    """
    # Unescape Java string literals (\" → ", \\ → \)
    def _unescape(s: str) -> str:
        return s.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")

    pattern = re.compile(
        r'By\.(id|xpath|cssSelector|name|className|tagName|linkText|partialLinkText)'
        r'\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)',
        re.DOTALL,
    )
    m = pattern.search(by_expr)
    if not m:
        return None

    strategy, raw_value = m.group(1), _unescape(m.group(2))

    if strategy == "id":
        return {
            "priority_locator": f"#{raw_value}",
            "priority_locator_type": "css",
            "fallback_locator": f"//*[@id='{raw_value}']",
            "fallback_locator_type": "xpath",
        }
    if strategy in ("cssSelector", "tagName", "className"):
        css = raw_value if strategy == "cssSelector" else f".{raw_value}" if strategy == "className" else raw_value
        return {
            "priority_locator": css,
            "priority_locator_type": "css",
            "fallback_locator": None,
            "fallback_locator_type": None,
        }
    if strategy == "xpath":
        return {
            "priority_locator": raw_value,
            "priority_locator_type": "xpath",
            "fallback_locator": None,
            "fallback_locator_type": None,
        }
    if strategy == "name":
        return {
            "priority_locator": f"//*[@name='{raw_value}']",
            "priority_locator_type": "xpath",
            "fallback_locator": f"[name='{raw_value}']",
            "fallback_locator_type": "css",
        }
    if strategy in ("linkText", "partialLinkText"):
        xpath = f"//a[normalize-space()='{raw_value}']" if strategy == "linkText" else f"//a[contains(.,'{raw_value}')]"
        return {
            "priority_locator": xpath,
            "priority_locator_type": "xpath",
            "fallback_locator": None,
            "fallback_locator_type": None,
        }
    return None


# Matches:  private final By txtAcctNo = By.id("...");
# Also:     protected By someField = By.xpath("...");
_FIELD_PATTERN = re.compile(
    r"(?:private|protected|public)?\s*(?:final\s+)?By\s+(\w+)\s*=\s*(By\.\w+\s*\(.*?\))\s*;",
    re.DOTALL,
)


def extract_locators(java_source: str) -> list[dict]:
    """Return list of raw locator dicts from a Java PO source string."""
    results = []
    seen_vars = set()
    for m in _FIELD_PATTERN.finditer(java_source):
        var_name = m.group(1)
        by_expr = m.group(2)
        if var_name in seen_vars:
            continue
        seen_vars.add(var_name)
        locator = _parse_by(by_expr)
        if locator is None:
            print(f"  [skip] Could not parse locator for variable: {var_name}", file=sys.stderr)
            continue
        field_name, prefix = _infer_field_name(var_name)
        locator["field_name"] = field_name
        locator["is_mandatory"] = prefix in _MANDATORY_PREFIXES
        locator["control_type"] = _PREFIX_CONTROL.get(prefix, "text_input")
        results.append(locator)
    return results


def write_csv(rows: list[dict], txn: str, screen: str, out_path: Path) -> None:
    fieldnames = [
        "transaction_number", "screen_name", "field_name",
        "priority_locator", "priority_locator_type",
        "fallback_locator", "fallback_locator_type",
        "ai_confidence_score", "is_mandatory", "control_type",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "transaction_number": txn,
                "screen_name": screen,
                "field_name": row["field_name"],
                "priority_locator": row["priority_locator"],
                "priority_locator_type": row["priority_locator_type"],
                "fallback_locator": row.get("fallback_locator") or "",
                "fallback_locator_type": row.get("fallback_locator_type") or "",
                "ai_confidence_score": 0.95,
                "is_mandatory": "true" if row["is_mandatory"] else "false",
                "control_type": row["control_type"],
            })
    print(f"Written {len(rows)} rows to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Java Selenium PO file to NBC Platform locator CSV")
    parser.add_argument("java_file", help="Path to the Java Page Object .java file")
    parser.add_argument("--txn", required=True, help="Transaction number, e.g. 001060")
    parser.add_argument("--screen", required=True, help="Screen name, e.g. 'Cash Withdrawal'")
    parser.add_argument("--out", help="Output CSV path (default: same dir as java_file, .csv extension)")
    parser.add_argument("--interactive", action="store_true",
                        help="Review and rename each inferred field name before writing")
    args = parser.parse_args()

    java_path = Path(args.java_file)
    if not java_path.exists():
        print(f"ERROR: File not found: {java_path}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out) if args.out else java_path.with_suffix(".csv")
    source = java_path.read_text(encoding="utf-8", errors="replace")
    rows = parse_java_po(source, args.txn, args.screen)

    if not rows:
        print("No locators found. Check the file uses 'By.id(...)' / 'By.xpath(...)' patterns.", file=sys.stderr)
        sys.exit(1)

    print(f"\nFound {len(rows)} locators in {java_path.name}:\n")
    for i, row in enumerate(rows):
        print(f"  {i+1:2d}. {row['field_name']:<30} {row['priority_locator_type']:<6} {row['priority_locator']}")

    if args.interactive:
        print("\nEnter new name to rename, or press Enter to keep:\n")
        for row in rows:
            new_name = input(f"  '{row['field_name']}' → ").strip()
            if new_name:
                row["field_name"] = new_name

    write_csv(rows, args.txn, args.screen, out_path)
    print(f"\nUpload this file via: Manage Locators -> Upload -> select CSV")


if __name__ == "__main__":
    main()
