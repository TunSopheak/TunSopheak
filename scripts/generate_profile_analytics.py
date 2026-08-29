#!/usr/bin/env python3
"""Generate a self-hosted GitHub profile analytics SVG using the standard library."""

from __future__ import annotations

import html
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USERNAME = os.getenv("GITHUB_USERNAME", "TunSopheak")
TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
OUTPUT = Path("assets/profile-analytics.svg")
CAMBODIA_TZ = timezone(timedelta(hours=7))

# Official GitHub language colors
LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "C": "#555555",
    "C++": "#f34b7d",
    "Java": "#b07219",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Shell": "#89e051",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "PHP": "#4F5D95",
    "Ruby": "#701516",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Dart": "#00B4AB",
    "Tcl": "#e4cc98",
    "Vue": "#41b883",
    "SCSS": "#c6538c",
    "Dockerfile": "#384d54",
    "Astro": "#ff5a00",
}


def api_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    if not TOKEN:
        raise RuntimeError("GH_TOKEN or GITHUB_TOKEN is required")

    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "TunSopheak-profile-analytics",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API HTTP {exc.code}: {details[:600]}") from exc


def fetch_contributions() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
                weekday
              }
            }
          }
        }
      }
    }
    """

    result = api_json(
        "https://api.github.com/graphql",
        method="POST",
        payload={
            "query": query,
            "variables": {
                "login": USERNAME,
                "from": f"{start.isoformat()}T00:00:00Z",
                "to": f"{today.isoformat()}T23:59:59Z",
            },
        },
    )

    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {result['errors']}")

    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {USERNAME}")

    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [day for week in weeks for day in week["contributionDays"]]
    days.sort(key=lambda row: row["date"])
    return days


def fetch_language_totals() -> dict[str, int]:
    repos = api_json(
        f"https://api.github.com/users/{USERNAME}/repos?per_page=100&type=owner&sort=updated"
    )
    totals: dict[str, int] = defaultdict(int)

    for repo in repos:
        if repo.get("fork") or repo.get("private") or repo.get("archived"):
            continue
        languages_url = repo.get("languages_url")
        if not languages_url:
            continue
        for language, size in api_json(languages_url).items():
            totals[str(language)] += int(size)

    return dict(totals)


def contribution_stats(days: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    counts = [int(day["contributionCount"]) for day in days]
    total = sum(counts)
    active_days = sum(1 for value in counts if value > 0)

    longest = run = 0
    for value in counts:
        if value > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    by_date = {
        date.fromisoformat(day["date"]): int(day["contributionCount"]) for day in days
    }

    cursor = datetime.now(timezone.utc).date()
    if by_date.get(cursor, 0) == 0:
        cursor -= timedelta(days=1)

    current = 0
    while by_date.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    return total, active_days, longest, current


def weekly_series(days: list[dict[str, Any]], weeks: int = 26) -> list[tuple[date, int]]:
    parsed = [
        (date.fromisoformat(day["date"]), int(day["contributionCount"])) for day in days
    ]
    parsed = parsed[-weeks * 7 :]

    result: list[tuple[date, int]] = []
    for index in range(0, len(parsed), 7):
        chunk = parsed[index : index + 7]
        if chunk:
            result.append((chunk[-1][0], sum(value for _, value in chunk)))
    return result


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def text(x: float, y: float, value: object, css: str, anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{css}" text-anchor="{anchor}">'
        f"{esc(value)}</text>"
    )


def build_svg(days: list[dict[str, Any]], languages: dict[str, int]) -> str:
    total, active_days, longest, current = contribution_stats(days)
    weekly = weekly_series(days)
    top_languages = sorted(languages.items(), key=lambda item: item[1], reverse=True)[:5]
    language_total = sum(value for _, value in top_languages) or 1
    refreshed = datetime.now(CAMBODIA_TZ).strftime("%d %b %Y · %H:%M")

    width, height = 1040, 760

    # Chart area
    chart_x, chart_y = 72, 278
    chart_w, chart_h = 896, 210

    values = [value for _, value in weekly] or [0]
    rounded_max = max(5, int(math.ceil(max(max(values), 1) / 5.0) * 5))
    denominator = max(len(weekly) - 1, 1)

    points: list[tuple[float, float]] = []
    for index, (_, value) in enumerate(weekly):
        x = chart_x + chart_w * index / denominator
        y = chart_y + chart_h - (value / rounded_max) * chart_h
        points.append((x, y))

    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points) if points else ""
    area = (
        path
        + f" L {points[-1][0]:.1f} {chart_y + chart_h:.1f} L {points[0][0]:.1f} {chart_y + chart_h:.1f} Z"
        if points
        else ""
    )

    peak_idx = min(range(len(points)), key=lambda i: points[i][1]) if points else 0

    parts = [
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{esc(USERNAME)} · GitHub Activity</title>
<desc id="desc">Live contribution analytics and language distribution</desc>

<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#09090b"/>
    <stop offset="100%" stop-color="#0c0c0f"/>
  </linearGradient>

  <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="#3b82f6"/>
    <stop offset="100%" stop-color="#a78bfa"/>
  </linearGradient>

  <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.22"/>
    <stop offset="100%" stop-color="#3b82f6" stop-opacity="0"/>
  </linearGradient>

  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="#3b82f6"/>
    <stop offset="100%" stop-color="#8b5cf6"/>
  </linearGradient>

  <style>
    .title {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 22px; font-weight: 600; fill: #fafafa; letter-spacing: -0.3px; }}
    .subtitle {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 13px; font-weight: 450; fill: #71717a; }}
    .metric {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 28px; font-weight: 650; fill: #fafafa; letter-spacing: -0.5px; }}
    .metricLabel {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 11px; font-weight: 500; fill: #71717a; letter-spacing: 0.4px; }}
    .section {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 13px; font-weight: 550; fill: #a1a1aa; letter-spacing: 0.2px; }}
    .axis {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 11px; font-weight: 450; fill: #52525b; }}
    .lang {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 13px; font-weight: 500; fill: #e4e4e7; }}
    .pct {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 12px; font-weight: 500; fill: #71717a; }}
    .footer {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; font-size: 11.5px; font-weight: 450; fill: #52525b; }}
  </style>
</defs>

<!-- Background -->
<rect width="{width}" height="{height}" rx="20" fill="url(#bg)" stroke="#27272a" stroke-width="1"/>

<!-- Header -->
{text(40, 42, "GitHub Activity", "title")}
{text(40, 64, f"@{USERNAME} · Last 12 months", "subtitle")}
{text(1000, 42, refreshed, "subtitle", "end")}

<!-- Subtle top accent -->
<rect x="40" y="80" width="80" height="2" rx="1" fill="url(#accent)"/>
"""
    ]

    # ========== METRIC CARDS ==========
    metrics = [
        (total, "Contributions"),
        (active_days, "Active days"),
        (f"{longest}d", "Longest streak"),
        (f"{current}d", "Current streak"),
    ]

    card_w = 230
    gap = 16
    start_x = 40

    for i, (value, label) in enumerate(metrics):
        x = start_x + i * (card_w + gap)

        # Card
        parts.append(
            f'<rect x="{x}" y="100" width="{card_w}" height="92" rx="12" fill="#18181b" stroke="#27272a"/>'
        )
        # Value
        parts.append(text(x + 20, 148, value, "metric"))
        # Label
        parts.append(text(x + 20, 172, label, "metricLabel"))

    # ========== CHART ==========
    parts.append(text(40, 230, "CONTRIBUTION TREND", "section"))

    # Chart container
    parts.append(
        '<rect x="40" y="246" width="960" height="250" rx="14" fill="#18181b" stroke="#27272a"/>'
    )

    # Horizontal grid
    for step in range(5):
        y = chart_y + chart_h * step / 4
        val = round(rounded_max * (1 - step / 4))
        parts.append(
            f'<line x1="{chart_x}" y1="{y:.1f}" x2="{chart_x + chart_w}" y2="{y:.1f}" stroke="#27272a" stroke-width="1"/>'
        )
        parts.append(text(chart_x - 10, y + 4, val, "axis", "end"))

    if area:
        parts.append(f'<path d="{area}" fill="url(#areaGrad)"/>')
        parts.append(
            f'<path d="{path}" fill="none" stroke="url(#lineGrad)" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>'
        )

        for i, (x, y) in enumerate(points):
            if i == peak_idx:
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="#3b82f6" opacity="0.2"/>'
                )
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.8" fill="#93c5fd" stroke="#09090b" stroke-width="2"/>'
                )
            else:
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#60a5fa" stroke="#09090b" stroke-width="1.5"/>'
                )

    # X labels
    for index, (week_date, _) in enumerate(weekly):
        if index % 5 == 0 or index == len(weekly) - 1:
            x = chart_x + chart_w * index / denominator
            parts.append(
                text(x, chart_y + chart_h + 22, week_date.strftime("%b %d"), "axis", "middle")
            )

    # ========== LANGUAGES ==========
    parts.append(text(40, 530, "TOP LANGUAGES", "section"))

    start_y = 552
    for i, (lang, size) in enumerate(top_languages):
        y = start_y + i * 28
        pct = size / language_total * 100
        bar_w = 720 * (pct / 100)
        color = LANGUAGE_COLORS.get(lang, "#3b82f6")

        # Language name + colored dot
        parts.append(f'<circle cx="48" cy="{y + 6}" r="4.5" fill="{color}"/>')
        parts.append(text(62, y + 10, lang, "lang"))

        # Track
        parts.append(
            f'<rect x="200" y="{y}" width="720" height="10" rx="5" fill="#27272a"/>'
        )
        # Fill
        parts.append(
            f'<rect x="200" y="{y}" width="{max(bar_w, 8):.1f}" height="10" rx="5" fill="{color}"/>'
        )

        # Percentage
        parts.append(text(940, y + 10, f"{pct:.1f}%", "pct"))

    # Footer
    parts.append(
        text(1000, 732, "Public repositories only · Synced via GitHub Actions", "footer", "end")
    )

    parts.append("</svg>\n")
    return "".join(parts)


def main() -> int:
    try:
        days = fetch_contributions()
        languages = fetch_language_totals()
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(build_svg(days, languages), encoding="utf-8", newline="\n")
        print(f"Generated {OUTPUT} for @{USERNAME}.")
        return 0
    except Exception as exc:
        print(f"WARNING: Analytics were not regenerated: {exc}", file=sys.stderr)
        if OUTPUT.exists():
            print(f"Keeping existing {OUTPUT}.")
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
