#!/usr/bin/env python3
"""Generate a self-hosted SVG dashboard for a GitHub profile README.

Uses only Python's standard library. Public contribution data comes from the
GitHub GraphQL API and language data comes from the GitHub REST API.
"""

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


def api_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    if not TOKEN:
        raise RuntimeError("GH_TOKEN or GITHUB_TOKEN is required")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
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
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API HTTP {exc.code}: {body[:600]}") from exc


def fetch_contributions() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
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
    active_days = sum(1 for count in counts if count > 0)

    longest = 0
    run = 0
    for count in counts:
        if count > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    by_date = {date.fromisoformat(day["date"]): int(day["contributionCount"]) for day in days}
    cursor = datetime.now(timezone.utc).date()
    if by_date.get(cursor, 0) == 0:
        cursor -= timedelta(days=1)
    current = 0
    while by_date.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)
    return total, active_days, longest, current


def weekly_series(days: list[dict[str, Any]], weeks: int = 26) -> list[tuple[date, int]]:
    parsed = [(date.fromisoformat(day["date"]), int(day["contributionCount"])) for day in days]
    parsed = parsed[-weeks * 7 :]
    series: list[tuple[date, int]] = []
    for index in range(0, len(parsed), 7):
        chunk = parsed[index : index + 7]
        if chunk:
            series.append((chunk[-1][0], sum(value for _, value in chunk)))
    return series


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def svg_text(x: float, y: float, text: object, css_class: str, anchor: str = "start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{css_class}" text-anchor="{anchor}">{esc(text)}</text>'


def build_svg(days: list[dict[str, Any]], languages: dict[str, int]) -> str:
    total, active_days, longest, current = contribution_stats(days)
    weekly = weekly_series(days)
    top_languages = sorted(languages.items(), key=lambda item: item[1], reverse=True)[:6]
    language_total = sum(value for _, value in top_languages) or 1
    updated = datetime.now(CAMBODIA_TZ).strftime("%d %b %Y · %H:%M ICT")

    width, height = 1040, 760
    chart_x, chart_y, chart_w, chart_h = 72, 258, 896, 258
    values = [value for _, value in weekly] or [0]
    max_value = max(max(values), 1)
    rounded_max = max(5, int(math.ceil(max_value / 5.0) * 5))

    points: list[tuple[float, float]] = []
    denominator = max(len(weekly) - 1, 1)
    for index, (_, value) in enumerate(weekly):
        x = chart_x + chart_w * index / denominator
        y = chart_y + chart_h - (value / rounded_max) * chart_h
        points.append((x, y))

    if points:
        path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)
        area = path + f" L {points[-1][0]:.1f} {chart_y + chart_h:.1f} L {points[0][0]:.1f} {chart_y + chart_h:.1f} Z"
    else:
        path = ""
        area = ""

    parts: list[str] = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{esc(USERNAME)} live GitHub analytics</title>
<desc id="desc">Automatically generated contribution summary, weekly contribution line chart, and public repository language distribution.</desc>
<defs>
  <linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#111827"/></linearGradient>
  <linearGradient id="line" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1f6feb"/><stop offset="1" stop-color="#79c0ff"/></linearGradient>
  <linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#58a6ff" stop-opacity="0.38"/><stop offset="1" stop-color="#58a6ff" stop-opacity="0.02"/></linearGradient>
  <style>
    .title {{ font: 750 28px 'Segoe UI', Arial, sans-serif; fill: #f0f6fc; }}
    .subtitle {{ font: 500 15px 'Segoe UI', Arial, sans-serif; fill: #8b949e; }}
    .metric {{ font: 750 30px 'Segoe UI', Arial, sans-serif; fill: #f0f6fc; }}
    .metricLabel {{ font: 600 13px 'Segoe UI', Arial, sans-serif; fill: #8b949e; letter-spacing: .6px; }}
    .section {{ font: 700 18px 'Segoe UI', Arial, sans-serif; fill: #c9d1d9; }}
    .axis {{ font: 500 12px 'Segoe UI', Arial, sans-serif; fill: #6e7681; }}
    .language {{ font: 600 14px 'Segoe UI', Arial, sans-serif; fill: #c9d1d9; }}
    .percent {{ font: 600 13px 'Segoe UI', Arial, sans-serif; fill: #8b949e; }}
  </style>
</defs>
<rect width="{width}" height="{height}" rx="24" fill="url(#background)" stroke="#30363d"/>
<circle cx="918" cy="72" r="125" fill="#1f6feb" opacity="0.10"/>
{svg_text(44, 52, 'Live GitHub Analytics', 'title')}
{svg_text(44, 80, f'Public activity for @{USERNAME} · Automatically generated in this repository', 'subtitle')}
{svg_text(996, 52, updated, 'subtitle', 'end')}
''']

    metrics = [
        ("Contributions", total),
        ("Active days", active_days),
        ("Longest streak", f"{longest} days"),
        ("Current streak", f"{current} days"),
    ]
    card_y, card_h, gap = 108, 104, 16
    card_w = (width - 88 - gap * 3) / 4
    for index, (label, value) in enumerate(metrics):
        x = 44 + index * (card_w + gap)
        parts.append(f'<rect x="{x:.1f}" y="{card_y}" width="{card_w:.1f}" height="{card_h}" rx="16" fill="#161b22" stroke="#30363d"/>')
        parts.append(svg_text(x + 20, card_y + 43, value, "metric"))
        parts.append(svg_text(x + 20, card_y + 74, label.upper(), "metricLabel"))

    parts.append(svg_text(44, 248, "Contribution trend · latest 26 weeks", "section"))
    parts.append(f'<rect x="44" y="260" width="952" height="292" rx="18" fill="#161b22" stroke="#30363d"/>')

    for step in range(5):
        y = chart_y + chart_h * step / 4
        value = round(rounded_max * (1 - step / 4))
        parts.append(f'<line x1="{chart_x}" y1="{y:.1f}" x2="{chart_x + chart_w}" y2="{y:.1f}" stroke="#21262d" stroke-width="1"/>')
        parts.append(svg_text(chart_x - 14, y + 4, value, "axis", "end"))

    if area:
        parts.append(f'<path d="{area}" fill="url(#area)"/>')
        parts.append(f'<path d="{path}" fill="none" stroke="url(#line)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#79c0ff" stroke="#0d1117" stroke-width="2"/>')

    for index, (week_date, _) in enumerate(weekly):
        if index % 5 == 0 or index == len(weekly) - 1:
            x = chart_x + chart_w * index / denominator
            parts.append(svg_text(x, chart_y + chart_h + 25, week_date.strftime("%b %d"), "axis", "middle"))

    parts.append(svg_text(44, 590, "Public repository language distribution", "section"))
    start_y = 620
    for index, (language, size) in enumerate(top_languages):
        row_y = start_y + index * 21
        pct = size / language_total * 100
        bar_x, bar_w = 226, 650
        filled = bar_w * pct / 100
        parts.append(svg_text(44, row_y + 12, language, "language"))
        parts.append(f'<rect x="{bar_x}" y="{row_y}" width="{bar_w}" height="12" rx="6" fill="#21262d"/>')
        parts.append(f'<rect x="{bar_x}" y="{row_y}" width="{max(filled, 3):.1f}" height="12" rx="6" fill="#1f6feb"/>')
        parts.append(svg_text(900, row_y + 12, f"{pct:.1f}%", "percent"))

    parts.append(svg_text(996, 738, "Language usage reflects public repository bytes—not proficiency.", "subtitle", "end"))
    parts.append("</svg>\n")
    return "".join(parts)


def main() -> int:
    try:
        days = fetch_contributions()
        languages = fetch_language_totals()
        svg = build_svg(days, languages)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(svg, encoding="utf-8", newline="\n")
        print(f"Generated {OUTPUT} for @{USERNAME} with {len(days)} contribution days.")
        return 0
    except Exception as exc:  # Preserve the last good image if GitHub has a temporary outage.
        print(f"WARNING: Profile analytics were not regenerated: {exc}", file=sys.stderr)
        if OUTPUT.exists():
            print(f"Keeping existing {OUTPUT}.")
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
