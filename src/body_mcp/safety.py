"""Body-MCP safety patterns and detection helpers.

Body-MCP must NEVER bypass logins, CAPTCHAs, bot checks, rate limits,
paywalls or access controls. These detectors classify what is on screen/page
so the server can STOP and hand control back to the human.
"""
import re

# Sensitive pages: login, OTP, payment, card data, etc.
SENSITIVE_PATTERNS = [
    r"\bpass(word|wd)\b",
    r"\bpin\b",
    r"\botp\b",
    r"\bone[- ]time\b",
    r"\bverification code\b",
    r"\bsecurity code\b",
    r"\bcard number\b",
    r"\bcard (?:exp|expiry)\b",
    r"\bexpiry\b",
    r"\bcvv\b",
    r"\bcvc\b",
    r"\bpayment\b",
    r"\bcheckout\b",
    r"\bbilling\b",
    r"\bcredit card\b",
    r"\bdebit card\b",
    r"\bsign[- ]?in\b",
    r"\blog[- ]?in\b",
    r"\btwo[- ]factor\b",
    r"\b2fa\b",
    r"\bsecret\b",
]

# Access restrictions: anything that says "prove you are human / slow down".
RESTRICTION_PATTERNS = [
    r"\bcaptcha\b",
    r"\brecaptcha\b",
    r"\bverify (that )?you are (?:a )?human\b",
    r"\bare you (?:a )?human\b",
    r"\bunusual traffic\b",
    r"\baccess denied\b",
    r"\bpermission denied\b",
    r"\brate limit(?:ed|ing)?\b",
    r"\btoo many requests\b",
    r"\b429\b",
    r"\bpaywall\b",
    r"\bsubscribe to (?:continue|read)\b",
    r"\b403\b",
    r"\bforbidden\b",
    r"\bblocked (?:your|this) (?:request|ip|account)\b",
    r"\bautomated (?:queries|requests|access)\b",
]

# Buttons that change the world. Clicking one requires a fresh reflex_ask() approval.
DANGEROUS_BUTTON_PATTERNS = [
    r"\bsubmit\b",
    r"\bpay\b",
    r"\bpay now\b",
    r"\bbuy\b",
    r"\bpurchase\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bsend\b",
    r"\bpost\b",
    r"\bpublish\b",
    r"\bconfirm\b",
    r"\bconfirm purchase\b",
    r"\bplace (?:order|booking)\b",
    r"\bdownload\b",
    r"\bwire\b",
    r"\btransfer\b",
]

# Fields that must never be read or typed by the body.
SENSITIVE_FIELD_PATTERNS = [
    r"pass(word|wd)",
    r"otp",
    r"one[-_. ]?time",
    r"verification",
    r"cardnumber|card[-_. ]?num|creditcard|credit card",
    r"cc[-_. ](number|csc|cvc|exp|exp-month|exp-year|type|name)",
    r"cc[-_. ]num",
    r"cvv|cvc",
    r"expiry|exp[-_. ]?date",
    r"card[-_. ]?exp",
    r"security[-_. ]?code",
]


def _hits(patterns: list[str], text: str) -> list[str]:
    found = []
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            found.append(pat)
    return found


def scan_text(text: str) -> dict:
    """Classify page/screen text. Returns hits and the mode to enter."""
    text = text or ""
    sensitive = _hits(SENSITIVE_PATTERNS, text)
    restricted = _hits(RESTRICTION_PATTERNS, text)
    return {
        "sensitive": bool(sensitive),
        "sensitive_hits": sensitive,
        "restricted": bool(restricted),
        "restriction_hits": restricted,
        "mode": "restricted" if restricted else ("sensitive" if sensitive else "normal"),
    }


def is_dangerous_label(label: str) -> bool:
    return bool(_hits(DANGEROUS_BUTTON_PATTERNS, label or ""))


def is_sensitive_field(attrs: dict) -> bool:
    """attrs: {'type','name','id','autocomplete','placeholder'} of a form control."""
    if (attrs.get("type") or "").lower() == "password":
        return True
    haystack = " ".join(str(attrs.get(k, "")) for k in ("name", "id", "autocomplete", "placeholder"))
    return bool(_hits(SENSITIVE_FIELD_PATTERNS, haystack))
