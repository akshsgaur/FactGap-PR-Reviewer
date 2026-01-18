"""Intent classification for query routing"""

import re
import logging
from enum import Enum
from typing import Dict, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class QueryIntent(Enum):
    """Query intent categories for retrieval routing"""
    STANDARDS_POLICY = "standards_policy"
    IMPLEMENTATION_DEBUG = "implementation_debug"
    PROCESS = "process"
    GENERAL = "general"


@dataclass
class IntentResult:
    """Result of intent classification"""
    intent: QueryIntent
    confidence: float
    matched_keywords: Set[str]
    scope_weights: Dict[str, float]


# Keyword patterns for each intent
INTENT_KEYWORDS: Dict[QueryIntent, Set[str]] = {
    QueryIntent.STANDARDS_POLICY: {
        "standard", "standards", "policy", "policies", "guideline", "guidelines",
        "convention", "conventions", "how do we", "how we", "best practice",
        "best practices", "naming", "lint", "linting", "style", "style guide",
        "code style", "formatting", "rule", "rules", "should we", "must we",
        "requirement", "requirements", "compliance", "compliant",
    },
    QueryIntent.IMPLEMENTATION_DEBUG: {
        "error", "errors", "bug", "bugs", "failing", "fail", "failed",
        "stack trace", "stacktrace", "traceback", "exception", "fix",
        "fixing", "why", "implement", "implementing", "implementation",
        "function", "class", "method", "how does", "how do i", "how to",
        "what does", "where is", "debug", "debugging", "issue", "problem",
        "broken", "crash", "crashing", "undefined", "null", "none",
        "typeerror", "valueerror", "keyerror", "attributeerror",
    },
    QueryIntent.PROCESS: {
        "deploy", "deployment", "deploying", "incident", "incidents",
        "runbook", "runbooks", "pr process", "pull request process",
        "approval", "approvals", "approve", "merge", "merging",
        "release", "releasing", "rollback", "rollout", "pipeline",
        "ci", "cd", "ci/cd", "workflow", "workflows", "review process",
        "code review", "on-call", "oncall", "pager", "alert", "alerts",
    },
}

# Scope weights by intent
# Higher weight = more importance for that scope
INTENT_SCOPE_WEIGHTS: Dict[QueryIntent, Dict[str, float]] = {
    QueryIntent.STANDARDS_POLICY: {
        "notion": 1.5,
        "repo_doc": 1.3,
        "code": 0.7,
        "diff": 0.5,
    },
    QueryIntent.IMPLEMENTATION_DEBUG: {
        "code": 1.5,
        "diff": 1.4,
        "repo_doc": 1.0,
        "notion": 0.6,
    },
    QueryIntent.PROCESS: {
        "notion": 1.5,
        "repo_doc": 1.4,
        "code": 0.5,
        "diff": 0.4,
    },
    QueryIntent.GENERAL: {
        "code": 1.0,
        "diff": 1.0,
        "repo_doc": 1.0,
        "notion": 1.0,
    },
}


class IntentClassifier:
    """Rules-based intent classifier for query routing"""

    def __init__(self):
        # Compile regex patterns for efficient matching
        self._patterns: Dict[QueryIntent, re.Pattern] = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            # Build pattern that matches any keyword (case-insensitive)
            # Use word boundaries for more accurate matching
            escaped = [re.escape(kw) for kw in keywords]
            pattern = r'\b(' + '|'.join(escaped) + r')\b'
            self._patterns[intent] = re.compile(pattern, re.IGNORECASE)

    def classify(self, query: str) -> IntentResult:
        """
        Classify query intent using keyword matching.

        Returns the intent with the most keyword matches,
        with confidence based on match density.
        """
        query_lower = query.lower()
        query_words = len(query.split())

        # Count matches per intent
        intent_matches: Dict[QueryIntent, Set[str]] = {}
        for intent, pattern in self._patterns.items():
            matches = set(m.group().lower() for m in pattern.finditer(query_lower))
            intent_matches[intent] = matches

        # Find intent with most matches
        best_intent = QueryIntent.GENERAL
        best_count = 0
        best_matches: Set[str] = set()

        for intent, matches in intent_matches.items():
            if len(matches) > best_count:
                best_count = len(matches)
                best_intent = intent
                best_matches = matches

        # Calculate confidence (0.0 to 1.0)
        # Based on match count relative to query length
        if best_count == 0:
            confidence = 0.0
        else:
            # More matches = higher confidence, capped at 1.0
            confidence = min(1.0, best_count / max(1, query_words / 3))

        # Get scope weights for this intent
        scope_weights = INTENT_SCOPE_WEIGHTS.get(
            best_intent,
            INTENT_SCOPE_WEIGHTS[QueryIntent.GENERAL]
        )

        result = IntentResult(
            intent=best_intent,
            confidence=confidence,
            matched_keywords=best_matches,
            scope_weights=scope_weights,
        )

        logger.debug(
            f"Intent classification: query='{query[:50]}...' "
            f"intent={best_intent.value} confidence={confidence:.2f} "
            f"matches={best_matches}"
        )

        return result

    def get_scope_weights(self, intent: QueryIntent) -> Dict[str, float]:
        """Get scope weights for a given intent"""
        return INTENT_SCOPE_WEIGHTS.get(
            intent,
            INTENT_SCOPE_WEIGHTS[QueryIntent.GENERAL]
        )
