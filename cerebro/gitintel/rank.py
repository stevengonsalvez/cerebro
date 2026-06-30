from __future__ import annotations

import math

from .models import GitHubRepoCandidate, GitHubUserCandidate, SearchPlan


def _terms(plan: SearchPlan) -> list[str]:
    return [t.lower() for t in plan.semantic_terms + plan.exact_terms if t]


def rank_repositories(candidates: list[GitHubRepoCandidate], plan: SearchPlan) -> list[GitHubRepoCandidate]:
    terms = _terms(plan)
    for c in candidates:
        haystack = " ".join([
            c.full_name, c.description, c.language, " ".join(c.topics),
            c.readme_excerpt[:1000],
        ]).lower()
        matches = [t for t in terms if t.lower() in haystack]
        exact = 1.0 if any(t.lower() in c.full_name.lower() for t in plan.exact_terms) else 0.0
        coverage = len(set(matches)) / max(len(set(terms)), 1)
        popularity = min(math.log10(max(c.stars, 0) + 1) / 5, 1)
        activity = 0.2 if c.pushed_at or c.updated_at else 0
        momentum = max(c.momentum_score, c.growth_score)
        novelty = max(1 - popularity, 0) if momentum else 0
        c.exact_score = exact
        c.semantic_score = coverage
        c.activity_score = activity
        c.score = round(
            exact * 0.25
            + coverage * 0.25
            + momentum * 0.30
            + popularity * 0.10
            + activity * 0.05
            + novelty * 0.05,
            4,
        )
        reasons = []
        if exact:
            reasons.append("exact name/entity match")
        if matches:
            reasons.append("matched " + ", ".join(sorted(set(matches))[:5]))
        if c.growth_reason:
            reasons.append(c.growth_reason)
        if c.stars:
            reasons.append(f"{c.stars} stars")
        if c.language:
            reasons.append(c.language)
        c.reason = "; ".join(reasons) or "GitHub candidate"
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def rank_users(candidates: list[GitHubUserCandidate], plan: SearchPlan) -> list[GitHubUserCandidate]:
    terms = _terms(plan)
    for c in candidates:
        haystack = " ".join([c.login, c.name, c.bio]).lower()
        matches = [t for t in terms if t in haystack]
        exact = 1.0 if any(t.lower() == c.login.lower() for t in plan.exact_terms) else 0.0
        coverage = len(set(matches)) / max(len(set(terms)), 1)
        popularity = min(math.log10(max(c.followers, 0) + 1) / 5, 1)
        momentum = max(c.momentum_score, c.growth_score, c.portfolio_momentum_score)
        c.score = round(
            exact * 0.30
            + coverage * 0.25
            + momentum * 0.25
            + popularity * 0.10
            + c.portfolio_momentum_score * 0.10,
            4,
        )
        bits = []
        if exact:
            bits.append("exact login match")
        if matches:
            bits.append("matched " + ", ".join(sorted(set(matches))[:5]))
        if c.growth_reason:
            bits.append(c.growth_reason)
        if c.portfolio_momentum_score:
            bits.append(f"portfolio momentum {c.portfolio_momentum_score:.2f}")
        if c.followers:
            bits.append(f"{c.followers} followers")
        c.reason = "; ".join(bits) or "GitHub user candidate"
    return sorted(candidates, key=lambda c: c.score, reverse=True)
