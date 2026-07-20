"""PromptInjectionGuard — detect and block prompt injection attempts.

Provides multi-layer detection:
  1. **Regex patterns** — known injection patterns (SQL, XSS, command)
  2. **Role-play detection** — attempts to override system persona

Usage:
    guard = PromptInjectionGuard()
    result = guard.check("Ignore previous instructions and...")
    if not result.allowed:
        raise SecurityViolation(result.reason)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# Maximum length of text to process (prevents DoS via ultra-long prompts)
MAX_TEXT_LENGTH = 50000

# Unicode confusable mapping — Cyrillic lookalikes → Latin
CONFUSABLE_MAP: dict[str, str] = {
    'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H', 'І': 'I',
    'К': 'K', 'М': 'M', 'О': 'O', 'Р': 'P', 'Т': 'T', 'Х': 'X',
    'а': 'a', 'е': 'e', 'і': 'i', 'о': 'o', 'р': 'p', 'с': 'c',
    'у': 'y', 'х': 'x', 'ѕ': 's',
}

# Patterns for sensitive data that needs redaction in sanitize step
SECRET_REDACT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{17}[\dXx]\b"),                          # Chinese ID
    re.compile(r"\b1[3-9]\d{9}\b"),                            # Chinese phone
    re.compile(r"(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*\S{8,}", re.IGNORECASE),  # credentials
    re.compile(r"(password|passwd|secret|token|key)\s+is\s+\S{8,}", re.IGNORECASE),  # "password is ..."
    re.compile(r"BEGIN\s+(RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY.*?END\s+\w+\s+PRIVATE\s+KEY", re.DOTALL),   # private keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS key
    re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),  # credit card number
    re.compile(r"\b\d{4}[-\s]?\d{6}[-\s]?\d{5}\b"),           # Chinese ID-like
]


class SecurityViolation(Exception):
    """Raised when a security check fails."""
    pass


@dataclass
class SecurityResult:
    """Result of a security check."""
    allowed: bool = True
    reason: str = ""
    risk_score: float = 0.0  # 0.0 = safe, 1.0 = definitely malicious


# ── Known injection patterns (weighted by severity) ────────────────

INJECTION_PATTERNS: list[tuple[str, float, str]] = [
    # System prompt override (high severity)
    (r"ignore\s+(all\s+)?(previous|above)\s+(instructions|prompts|commands)", 0.9, "system prompt override"),
    (r"forget\s+(all\s+)?(previous|above)\s+(instructions|prompts)", 0.85, "memory wipe attempt"),
    (r"you\s+are\s+(not\s+)?(required\s+to|obligated\s+to)\s+(follow|obey)", 0.8, "role rejection"),

    # Role-play jailbreak (high severity)
    (r"(act\s+as|pretend\s+to\s+be|role\s*play\s+as)\s+(dan|devil|jailbreak|unfiltered)", 0.95, "jailbreak role-play"),
    (r"(hypothetical|fictional)\s+(scenario\s+where|situation\s+where)\s+(you\s+are|there\s+is\s+no)", 0.7, "hypothetical jailbreak"),

    # SQL injection (medium severity)
    (r"(\bDROP\s+TABLE|\bDELETE\s+FROM|\bINSERT\s+INTO|\bOR\s+1\s*=\s*1\b)", 0.8, "SQL injection pattern"),
    (r"('|\")(--| OR | AND | UNION)(\s+|--)", 0.75, "SQL injection — tautology"),

    # Command injection (medium severity)
    (r"(;|\||`|\$\(|\$\{)\s*(rm|wget|curl|bash|sh|python|nc|mkfs|dd)", 0.85, "command injection"),
    (r"\bexec\s*\(|\beval\s*\(|\bsystem\s*\(|\bpopen\s*\(", 0.8, "code execution function"),

    # XSS / HTML injection (low severity)
    (r"<script[^>]*>.*</script[^>]*>", 0.6, "XSS script tag"),
    (r"javascript\s*:", 0.5, "XSS javascript: URI"),
    (r"onerror\s*=|onload\s*=|onclick\s*=|onmouseover\s*=", 0.5, "XSS event handler"),

    # System prompt extraction (high severity — extended patterns)
    (r"(reveal|show|display|print|output|dump)\s+(your|the)\s+(system|internal|initial)\s+(prompt|instructions|message)", 0.8, "system prompt extraction"),
    (r"(what\s+(is|are)|tell\s+me|show)\s+(your|the)\s+(initial|first|system)\s+(prompt|message|instructions)", 0.75, "initial prompt extraction"),
    (r"repeat\s+(everything|all)\s+(above|below)\s+(this\s+)?(line|text|message|verbatim)", 0.8, "prompt repeat attack"),
    (r"\"?translate\"?\s+(to|into)\s+\w+\s*:.+ignore", 0.7, "translation-based bypass"),
    (r"output\s+(your|the)\s+(system|prompt|instructions)\s+(verbatim|exactly)", 0.8, "system prompt verbatim extraction"),
    (r"(initial|first|start).{0,20}(prompt|message|instruction|system)", 0.6, "initial prompt reference"),
    (r"(print|show|display|output)\s+the\s+prompt\s+you\s+(received|got)\s+(at|during)\s+(initialization|startup)", 0.7, "initialization prompt extraction"),

    # Multilingual injection (high severity — Chinese/Japanese/Korean/French)
    (r"(忽略|忽视|无视).{0,4}(所有|全部).{0,4}(指令|指示|命令)", 0.85, "Chinese: prompt override"),
    (r"(以前|上記).{0,4}(指示|命令|指令).{0,4}(無視|忽略|忽略)", 0.85, "Japanese/CN: ignore instructions"),
    (r"(이전|위).{0,4}(지시|명령|지침).{0,4}(무시|무력화)", 0.85, "Korean: ignore instructions"),
    (r"(ignore|ignorez|oubliez|négligez)\s+(toutes|tous)\s+(les\s+)?instructions", 0.85, "French: ignore instructions"),
    (r"(扮演|模拟|装作|充当).{0,4}(黑客|破解|自由|无限制|不受限)", 0.8, "Chinese: role-play jailbreak"),
    (r"(あなた|お前).{0,4}(制限|ルール|規則).{0,4}(無視|外す)", 0.8, "Japanese: role override"),

    # Sensitive data patterns (medium severity)
    (r"\b\d{17}[\dXx]\b", 0.7, "Chinese ID number (18 digits)"),
    (r"\b1[3-9]\d{9}\b", 0.7, "Chinese phone number"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", 0.5, "email address"),
    (r"\b(?:\d{3}-?\d{3,4}-?\d{4})\b", 0.5, "phone number pattern"),
    (r"(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*\S{8,}", 0.8, "credential/API key exposure"),
    (r"(password|passwd|secret|key)\s+is\s+\S{8,}", 0.7, "credential in plain text"),
    (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", 0.7, "credit card number"),
    (r"BEGIN\s+(RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY", 0.95, "private key exposure"),
    (r"AKIA[0-9A-Z]{16}", 0.85, "AWS access key ID"),

    # Mass extraction detection
    (r"(全部|所有|all|every|全部).{0,10}(数据|data|记录|records|用户|users)", 0.7, "mass data extraction attempt"),
    (r"(导出|export|dump|下载|download).{0,10}(全部|所有|all|every)", 0.7, "mass export attempt"),
    (r"(爬取|crawl|scrape|extract).{0,10}(所有|全部|all)", 0.7, "mass scraping attempt"),
]


class PromptInjectionGuard:
    """Multi-layer prompt injection detector.

    Args:
        patterns: Custom pattern list (defaults to INJECTION_PATTERNS).
        threshold: Minimum risk score to block (0.0–1.0, default 0.6).
    """

    def __init__(self, patterns: Optional[list[tuple[str, float, str]]] = None,
                 threshold: float = 0.6):
        self._patterns = patterns or INJECTION_PATTERNS
        self._threshold = threshold
        self._compiled: list[tuple[re.Pattern, float, str]] = [
            (re.compile(p, re.IGNORECASE), score, desc)
            for p, score, desc in self._patterns
        ]

    def check(self, text: str) -> SecurityResult:
        """Check text for prompt injection.

        Applies Unicode NFKC normalization and whitespace
        normalization before pattern matching.

        Args:
            text: The prompt text to check.

        Returns:
            SecurityResult with risk score and reason.
        """
        if not text:
            return SecurityResult(allowed=True)

        # Normalize Unicode (NFKC → folds confusables)
        normalized = unicodedata.normalize("NFKC", text)

        # Transliterate Cyrillic confusables to Latin
        normalized = ''.join(CONFUSABLE_MAP.get(c, c) for c in normalized)

        # Normalize ALL whitespace runs to single space
        normalized = re.sub(r"\s+", " ", normalized)

        # Also create a no-whitespace version (catches split-word attacks)
        no_space = re.sub(r"\s+", "", text)

        # Truncate to max length for processing
        if len(normalized) > MAX_TEXT_LENGTH:
            normalized = normalized[:MAX_TEXT_LENGTH]

        max_score = 0.0
        reasons = []

        # Check normalized text
        for pattern, score, desc in self._compiled:
            if pattern.search(normalized):
                max_score = max(max_score, score)
                reasons.append(f"{desc} (score={score})")

        # Also check no-whitespace version for split-word detection
        if max_score < self._threshold and len(no_space) > 0:
            # Lowercase for matching
            no_space_lower = no_space.lower()
            for pattern, score, desc in self._compiled:
                # Try to match after stripping all \s from the pattern too
                pattern_str = pattern.pattern
                stripped_pattern = pattern_str.replace(r"\s+", r"\s*")  # \s+ → \s*
                try:
                    relaxed = re.compile(stripped_pattern, re.IGNORECASE)
                    if relaxed.search(no_space_lower):
                        max_score = max(max_score, score)
                        reasons.append(f"{desc} (whitespace-stripped, score={score})")
                except Exception:
                    pass

        if max_score >= self._threshold:
            return SecurityResult(
                allowed=False,
                reason="; ".join(reasons),
                risk_score=max_score,
            )

        return SecurityResult(allowed=True, risk_score=max_score)

    def sanitize(self, text: str) -> str:
        """Sanitize text by removing dangerous patterns and redacting secrets.

        Replaces matched injection patterns with ``[REDACTED]`` markers.
        Secret patterns (IDs, keys, passwords) are redacted even when
        their score is below the threshold.
        """
        if not text:
            return ""

        # Always redact secrets regardless of threshold
        result = text
        for pat in SECRET_REDACT_PATTERNS:
            result = pat.sub("[REDACTED]", result)

        # Redact above-threshold injection patterns
        for pattern, score, desc in self._compiled:
            if score >= self._threshold:
                result = pattern.sub("[REDACTED]", result)
        return result
