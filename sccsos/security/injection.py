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
from dataclasses import dataclass, field
from typing import Optional


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
    (r"('|\"--)(\s*OR|\s*AND)(\s+|\s*--)", 0.75, "SQL injection — tautology"),

    # Command injection (medium severity)
    (r"(;|\||`|\$\(|\$\{)\s*(rm|wget|curl|bash|sh|python|nc|mkfs|dd)", 0.85, "command injection"),
    (r"\bexec\s*\(|\beval\s*\(|\bsystem\s*\(|\bpopen\s*\(", 0.8, "code execution function"),

    # XSS / HTML injection (low severity)
    (r"<script[^>]*>.*</script[^>]*>", 0.6, "XSS script tag"),
    (r"javascript\s*:", 0.5, "XSS javascript: URI"),
    (r"onerror\s*=|onload\s*=|onclick\s*=|onmouseover\s*=", 0.5, "XSS event handler"),

    # Data extraction (medium severity)
    (r"(reveal|show|display|print|output)\s+(your|the)\s+(system|internal)\s+(prompt|instructions)", 0.8, "system prompt extraction"),
    (r"(what\s+is|tell\s+me|show)\s+(your|the)\s+(initial|first|system)\s+(prompt|message)", 0.75, "initial prompt extraction"),
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

        Args:
            text: The prompt text to check.

        Returns:
            SecurityResult with risk score and reason.
        """
        if not text:
            return SecurityResult(allowed=True)

        max_score = 0.0
        reasons = []

        for pattern, score, desc in self._compiled:
            if pattern.search(text):
                max_score = max(max_score, score)
                reasons.append(f"{desc} (score={score})")

        if max_score >= self._threshold:
            return SecurityResult(
                allowed=False,
                reason="; ".join(reasons),
                risk_score=max_score,
            )

        return SecurityResult(allowed=True, risk_score=max_score)

    def sanitize(self, text: str) -> str:
        """Sanitize text by stripping known dangerous patterns.

        Replaces matched patterns with ``[REDACTED]`` markers.
        """
        result = text
        for pattern, score, desc in self._compiled:
            if score >= self._threshold:
                result = pattern.sub("[REDACTED]", result)
        return result
