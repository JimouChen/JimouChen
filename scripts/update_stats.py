#!/usr/bin/env python3
"""刷新 README 的 GitHub 统计区块（star 数 + 语言排行），零第三方部署依赖。

数据来源：GitHub REST API（Actions 里用内置 GITHUB_TOKEN，本地运行可不带 token，
但受匿名 60 次/小时限流约束）。

产出：
  1. assets/lang_stats.svg            语言分布条形图（tokyonight 配色）
  2. README.md 中 <!-- STATS:START --> 与 <!-- STATS:END --> 之间的区块
"""

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date
from xml.sax.saxutils import escape

# ---------------- 配置 ----------------
USER = "JimouChen"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO_ROOT, "README.md")
SVG_PATH = os.path.join(REPO_ROOT, "assets", "lang_stats.svg")
TOP_REPO_COUNT = 6  # 展示的最多 star 仓库数量

# tokyonight 配色
BG = "1a1b27"
TITLE_COLOR = "7aa2f7"
TEXT_COLOR = "c0caf5"
MUTED_COLOR = "a9b1d6"
TRACK_COLOR = "2f334d"
STAR_COLOR = "e0af68"

# GitHub Linguist 官方语言色
LANG_COLORS = {
    "Python": "3572A5", "Go": "00ADD8", "C++": "f34b7d", "C": "555555",
    "HTML": "e34c26", "JavaScript": "f1e05a", "TypeScript": "3178c6",
    "Vue": "41b883", "Dart": "00B4AB", "Java": "b07219", "Shell": "89e051",
    "CMake": "DA3434", "CSS": "563d7c", "Jinja": "a52a22", "Other": "8b949e",
}


def lang_color(name: str) -> str:
    return LANG_COLORS.get(name, LANG_COLORS["Other"])


# ---------------- 网络请求 ----------------
def http_json(url, token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "readme-stats-bot",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):  # 二次请求限流时短暂重试
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 403 and attempt < 2:
                import time
                time.sleep(2)
                continue
            raise


def fetch_repos(token=None):
    repos, page = [], 1
    while True:
        batch = http_json(
            f"https://api.github.com/users/{USER}/repos?per_page=100&page={page}", token)
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


def aggregate(repos, token=None):
    """返回 (总 star, 总 fork, 原创仓库列表, 语言字节数 dict)"""
    total_stars = sum(r["stargazers_count"] for r in repos)
    total_forks = sum(r["forks_count"] for r in repos)
    own = [r for r in repos if not r["fork"] and r["size"] > 0]

    lang_bytes: dict[str, int] = {}
    for r in own:
        for name, size in http_json(r["languages_url"], token).items():
            lang_bytes[name] = lang_bytes.get(name, 0) + size
    return total_stars, total_forks, own, lang_bytes


# ---------------- SVG 渲染 ----------------
def render_svg(lang_weights, title="Language Distribution"):
    """按权重渲染语言排行条形图。weight 可以是字节数或仓库数，只看占比。"""
    total = sum(lang_weights.values()) or 1
    # 占比排序，取前 8，其余连同输入中的 Other 一并合并到末尾的 Other
    items = sorted(lang_weights.items(), key=lambda x: -x[1])
    other = sum(v for n, v in items if n == "Other")
    items = [(n, v) for n, v in items if n != "Other"]
    if len(items) > 8:
        other += sum(v for _, v in items[8:])
        items = items[:8]
    if other:
        items.append(("Other", other))
    items = [(n, v, v / total * 100) for n, v in items]

    W, PAD = 620, 25
    bar_y, bar_h = 58, 14
    row_y0, row_h = 104, 28
    H = row_y0 + len(items) * row_h + 18

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" '
        f'fill="#{BG}" stroke="#{TRACK_COLOR}"/>',
        f'<text x="{PAD}" y="36" font-family="Segoe UI,Ubuntu,Sans-Serif" '
        f'font-size="16" font-weight="600" fill="#{TITLE_COLOR}">'
        f'{escape(title)}</text>',
    ]

    # 顶部堆叠条
    x = PAD
    inner_w = W - PAD * 2
    for name, _, pct in items:
        seg_w = inner_w * pct / 100
        parts.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{seg_w:.1f}" height="{bar_h}" '
            f'rx="{bar_h / 2}" fill="#{lang_color(name)}" fill-opacity="0.9"/>')
        x += seg_w

    # 排行榜行：色点 + 名称 + 进度条 + 百分比
    name_x, track_x, track_w = PAD + 12, 190, W - 190 - PAD - 58
    for i, (name, _, pct) in enumerate(items):
        y = row_y0 + i * row_h
        cy = y + 10
        parts.append(f'<circle cx="{PAD + 2}" cy="{cy}" r="5" fill="#{lang_color(name)}"/>')
        parts.append(
            f'<text x="{name_x}" y="{cy + 4}" font-family="Segoe UI,Ubuntu,Sans-Serif" '
            f'font-size="13" fill="#{TEXT_COLOR}">{escape(name)}</text>')
        bw = track_w * pct / 100
        parts.append(
            f'<rect x="{track_x}" y="{y + 4}" width="{track_w}" height="11" '
            f'rx="5.5" fill="#{TRACK_COLOR}"/>')
        if bw > 2:
            parts.append(
                f'<rect x="{track_x}" y="{y + 4}" width="{bw:.1f}" height="11" '
                f'rx="5.5" fill="#{lang_color(name)}"/>')
        parts.append(
            f'<text x="{W - PAD}" y="{cy + 4}" text-anchor="end" '
            f'font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="12.5" '
            f'fill="#{MUTED_COLOR}">{pct:.1f}%</text>')

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------- README 区块渲染 ----------------
def star_badge(repo: str, v: str) -> str:
    q = urllib.parse.urlencode({
        "style": "flat-square", "logo": "github",
        "label": "\u2b50", "labelColor": BG, "color": STAR_COLOR, "v": v,
    })
    return (f'<img src="https://img.shields.io/github/stars/{repo}?{q}" '
            f'alt="stars of {repo.split("/")[1]}"/>')


def render_readme_block(repos, v):
    """生成插在 <!-- STATS:START/END --> 之间的完整区块（纯 HTML，GitHub 可直接渲染）

    数值徽章用 shields.io 动态端点，label 只放文字，避免与动态值重复。
    """
    top = sorted(repos, key=lambda r: -r["stargazers_count"])
    top = [r for r in top if r["stargazers_count"] > 0][:TOP_REPO_COUNT]

    def pill(endpoint: str, label: str, color: str, logo: str = "github") -> str:
        q = urllib.parse.urlencode({
            "style": "for-the-badge", "logo": logo,
            "label": label, "labelColor": BG, "color": color, "v": v,
        })
        return f'<img src="https://img.shields.io/{endpoint}?{q}" alt="{label}"/>'

    pills = "  \n  ".join([
        pill(f"github/stars/{USER}", "Stars", "e0af68", "star"),
        pill(f"github/repos/{USER}", "Repos", "7aa2f7", "git"),
        pill(f"github/followers/{USER}", "Followers", "bb9af7"),
    ])

    # top 仓库 2 列网格
    rows = []
    for i in range(0, len(top), 2):
        cells = []
        for r in top[i:i + 2]:
            name = r["name"]
            cells.append(
                f'<td align="left" width="50%">'
                f'<a href="https://github.com/{USER}/{name}"><b>{name}</b></a>'
                f'<br/>{star_badge(f"{USER}/{name}", v)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return f"""<h2 align="center">⚡ GitHub Stats</h2>

<p align="center">
  {pills}
</p>

<p align="center">
  <img width="620" src="assets/lang_stats.svg?v={v}" alt="Language distribution"/>
</p>

<h3 align="center">🌟 Most Starred Repositories</h3>

<div align="center">
<table>
<tr><th align="center" width="50%">Repository</th><th align="center" width="50%">Repository</th></tr>
{chr(10).join(rows)}
</table>
</div>"""


def update_readme(block: str) -> bool:
    html = open(README_PATH, encoding="utf-8").read()
    new = f"<!-- STATS:START -->\n{block}\n<!-- STATS:END -->"
    if re.search(r"<!-- STATS:START -->.*?<!-- STATS:END -->", html, re.S):
        updated = re.sub(r"<!-- STATS:START -->.*?<!-- STATS:END -->", new, html, flags=re.S)
    else:
        updated = html + "\n" + new
    changed = updated != html
    if changed:
        open(README_PATH, "w", encoding="utf-8").write(updated)
    return changed


def main():
    token = os.environ.get("GITHUB_TOKEN")
    v = os.environ.get("STATS_VERSION") or date.today().strftime("%Y%m%d")

    repos = fetch_repos(token)
    total_stars, total_forks, own, lang_bytes = aggregate(repos, token)
    print(f"repos={len(repos)} stars={total_stars} forks={total_forks} "
          f"own={len(own)} langs={len(lang_bytes)}")

    os.makedirs(os.path.dirname(SVG_PATH), exist_ok=True)
    with open(SVG_PATH, "w", encoding="utf-8") as f:
        f.write(render_svg(lang_bytes))

    changed = update_readme(render_readme_block(own, v))
    print(f"readme updated: {changed}, version: {v}")


if __name__ == "__main__":
    main()
