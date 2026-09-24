#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
energy-rss -- 把「没有 RSS / RSS 被墙 / RSS 被反爬拦住」的中文能源电力站点,
变成 Inoreader 能稳定订阅的标准 RSS。

设计要点:
  1. 纯标准库, 零第三方依赖。GitHub Actions 里不用 pip install, 少一个会坏的环节。
  2. 抓不到就保留上一次的成品 (keep-last-good), 绝不把空 feed 覆盖上去。
  3. 同时产出 RSS、OPML 和一张带一键订阅按钮的网页。

用法:
  python build.py                 # 抓取并写入 docs/
  python build.py --dry-run       # 只抓取和打印, 不写文件
  python build.py --only zgdc,dwjs
  python build.py --max-items 30
"""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sources import SOURCES

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
FEED_DIR = DOCS / "feeds"
PLACEHOLDER_BASE = "https://YOUR-GITHUB-NAME.github.io/energy-rss"
DEFAULT_MAX_ITEMS = 60
REQUEST_GAP = 0.4
STATUS_PATH = DOCS / "status.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ==========================================================================
# 基础工具
# ==========================================================================

def http_get(url: str, *, referer: str | None = None, timeout: int = 30, retries: int = 3) -> bytes:
    """带重试的 GET。固定用 identity 编码, 省得处理 gzip。"""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(1.2 * attempt)
        finally:
            time.sleep(REQUEST_GAP)
    raise RuntimeError(f"请求失败 {url}: {type(last).__name__}: {last}")


def decode(raw: bytes) -> str:
    """按 XML 声明 / meta charset / 常见中文编码依次尝试解码。"""
    candidates: list[str] = []
    if re.match(rb"^\s*<\?xml", raw[:64]):
        m = re.search(rb'encoding\s*=\s*["\']([\w.\-]+)', raw[:200], re.I)
        if m:
            candidates.append(m.group(1).decode("ascii", "ignore"))
    m = re.search(rb'charset\s*=\s*["\']?([\w.\-]+)', raw[:6000], re.I)
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "gb18030", "gbk", "big5"]
    tried: set[str] = set()
    for enc in candidates:
        enc = enc.strip().lower()
        if not enc or enc in tried:
            continue
        tried.add(enc)
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def clean_ctrl(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def strip_tags(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    text = text.replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def esc(text: str) -> str:
    return (
        clean_ctrl(str(text))
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def cdata(text: str) -> str:
    return "<![CDATA[" + clean_ctrl(text).replace("]]>", "]]&gt;") + "]]>"


def rfc822(dt: datetime) -> str:
    """RSS 只认 RFC822 时间。没时区的按北京时间算。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return email.utils.format_datetime(dt)


_DATE_PATTERNS = (
    r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})",
    r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})",
    r"^(\d{4})-(\d{2})-(\d{2})",
    r"^(\d{4})/(\d{1,2})/(\d{1,2})",
    r"^(\d{4})(\d{2})(\d{2})$",
)


def parse_dt(value) -> datetime | None:
    """尽量把各种日期写法变成带 +08:00 的 datetime。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, TZ)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)
    except (TypeError, ValueError, IndexError):
        pass
    for pat in _DATE_PATTERNS:
        m = re.match(pat, text)
        if not m:
            continue
        parts = [int(x) for x in m.groups()]
        while len(parts) < 6:
            parts.append(0)
        try:
            return datetime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], tzinfo=TZ)
        except ValueError:
            return None
    return None


def make_item(title: str, link: str, date, summary: str = "", author: str = "") -> dict:
    return {
        "title": strip_tags(title),
        "link": str(link).strip(),
        "date": parse_dt(date),
        "summary": strip_tags(summary),
        "author": strip_tags(author),
    }


def finalize(items: list[dict], limit: int) -> list[dict]:
    """去重、丢掉垃圾条目、按时间倒序、截断。"""
    seen: set[str] = set()
    cleaned: list[dict] = []
    for it in items:
        title = it.get("title", "")
        link = it.get("link", "")
        if len(title) < 4 or not link.startswith("http"):
            continue
        link = link.split("#", 1)[0]
        # 有些站点(比如知网)给的链接带一次性令牌, 每次请求都不一样。
        # 这类源必须自己提供 stable_key, 否则同一篇文章每轮都会变成"新条目"。
        key = it.get("stable_key") or link
        if key in seen:
            continue
        seen.add(key)
        it["link"] = link
        it["guid"] = key
        cleaned.append(it)
    epoch = datetime(1970, 1, 1, tzinfo=TZ)
    cleaned.sort(key=lambda x: x.get("date") or epoch, reverse=True)
    return cleaned[:limit]


# ==========================================================================
# 各站点解析器: 每个都返回 (items, extra)
# ==========================================================================

def parse_nea(src: dict, _ctx: dict) -> tuple[list[dict], dict]:
    """国家能源局: 列表页里藏 datasource id, 真正的数据在同目录的 ds_<id>.json。

    这套页面是新华云做的, 列表由前端 Xhwpage 组件异步填充, 直接抓 HTML 只能
    拿到空 <ul>。但数据本身是完全公开的静态 JSON, 顺着 id 就能取到。
    """
    page = src["page"]
    page_html = decode(http_get(page))
    tag = re.search(r'<ul[^>]*id="showData0"[^>]*>', page_html)
    if not tag:
        raise RuntimeError("页面结构变了: 找不到 id=showData0 的容器")
    tag_html = tag.group(0)
    m_ds = re.search(r'data="datasource:([0-9a-fA-F]{32})"', tag_html)
    if not m_ds:
        raise RuntimeError("页面结构变了: 找不到 datasource id")
    m_pv = re.search(r'preview="([^"]*)"', tag_html)
    preview = m_pv.group(1) if m_pv else "ds_"
    json_url = urllib.parse.urljoin(page, f"./{preview}{m_ds.group(1)}.json")

    data = json.loads(decode(http_get(json_url, referer=page)))
    rows = data.get("datasource") or data.get("data") or []
    if not isinstance(rows, list):
        raise RuntimeError("JSON 结构变了: datasource 不是列表")

    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("title") or row.get("showTitle") or ""
        link = row.get("publishUrl") or row.get("sourceLink") or ""
        if not title or not link:
            continue
        items.append(
            make_item(
                title=title,
                link=urllib.parse.urljoin(json_url, str(link).strip()),
                date=row.get("publishTime") or row.get("publishDate"),
                summary=row.get("summary") or row.get("quote") or "",
                author=row.get("responsibleEditor") or row.get("editor") or "",
            )
        )
    return items, {"data_url": json_url, "raw_count": len(rows)}


def parse_csg(src: dict, _ctx: dict) -> tuple[list[dict], dict]:
    """南方电网: 静态列表页, 每年一个目录, 所以按年份模板从今年往回试。"""
    tpl = src["page_tpl"]
    now = datetime.now(TZ)
    last_error = "无"
    for year in (now.year, now.year - 1, now.year - 2):
        page = tpl.format(y=year)
        try:
            page_html = decode(http_get(page))
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        rows = re.findall(
            r'<span>(\d{4}-\d{2}-\d{2})</span>\s*<h2>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            page_html,
            re.S,
        )
        items = [
            make_item(
                title=label,
                link=urllib.parse.urljoin(page, html_mod.unescape(href)),
                date=date_text,
                author="南方电网",
            )
            for date_text, href, label in rows
        ]
        if items:
            return items, {"page": page}
    raise RuntimeError(f"列表页没有条目 (最后一次错误: {last_error})")


_BJX_LINK = re.compile(
    r'<a[^>]+href="(https?://([a-z0-9\-]+)\.bjx\.com\.cn/html/(\d{8})/(\d+)\.shtml)"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_BJX_DEAD_HOSTS = {"ex"}


def parse_bjx(src: dict, _ctx: dict) -> tuple[list[dict], dict]:
    """北极星: 从列表页抽文章链接, 日期直接来自 URL 里的 YYYYMMDD。

    注意 news.bjx.com.cn 挂阿里云 WAF, 会返回验证码页; 首页和大部分频道页正常。
    """
    page = src["page"]
    page_html = decode(http_get(page))
    low = page_html.lower()
    if "aliyun_waf" in low or "aliyuncaptcha" in low:
        raise RuntimeError("撞上阿里云 WAF 验证码 (该子域被保护), 换一个频道页")
    page_label = (urllib.parse.urlparse(page).hostname or "").split(".")[0]
    items = []
    hosts: set[str] = set()
    skipped = 0
    for m in _BJX_LINK.finditer(page_html):
        url, host, ymd, _aid, label = m.groups()
        # 北极星的文章都在 news 子域; ex 子域已失效会 404, 其余子域按频道页自身放宽
        if host in _BJX_DEAD_HOSTS or host not in {"news", page_label}:
            skipped += 1
            continue
        title = strip_tags(label)
        if len(title) < 6:
            continue
        hosts.add(host)
        items.append(make_item(title=title, link=url, date=ymd, author="北极星电力网"))
    if not items:
        raise RuntimeError("页面里没有解析出文章链接")
    return items, {"hosts": sorted(hosts), "skipped": skipped}


def _xml_tolerant(raw: bytes) -> bytes:
    """老式 RSS 里常有裸 & , ElementTree 会直接报错, 先修一层。"""
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
    return text.encode("utf-8")


def parse_cnki(src: dict, _ctx: dict) -> tuple[list[dict], dict]:
    """知网 RSS: 自己取回来重新装一遍, 绕开 Inoreader 抓取被拦的问题。"""
    raw = http_get(src["url"])
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(_xml_tolerant(raw))

    def pick(node, tag: str) -> str:
        el = node.find(tag)
        if el is None:
            el = node.find(f"{{*}}{tag}")
        return (el.text or "") if el is not None and el.text else ""

    items = []
    for node in root.iter("item"):
        title = pick(node, "title")
        link = pick(node, "link")
        if not title or not link:
            continue
        date = pick(node, "pubDate")
        item = make_item(
            title=title,
            link=link,
            date=date,
            summary=pick(node, "description"),
            author=pick(node, "author"),
        )
        # 知网链接里的 v= 参数每次请求都变, 用"标题+时间"算稳定标识
        stable = f"{src['id']}|{strip_tags(title)}|{date}"
        item["stable_key"] = "cnki-" + hashlib.sha1(stable.encode("utf-8")).hexdigest()
        items.append(item)
    if not items:
        raise RuntimeError("知网 RSS 里没有可用 item")
    return items, {"raw_count": len(items)}


PARSERS = {
    "nea": parse_nea,
    "csg": parse_csg,
    "bjx": parse_bjx,
    "cnki": parse_cnki,
}


# ==========================================================================
# 输出: RSS / OPML / 索引页
# ==========================================================================

def build_rss(src: dict, items: list[dict], self_url: str) -> str:
    # lastBuildDate 用最新条目的时间, 而不是"本次运行时间" ——
    # 这样只要内容没变, 生成的文件就是逐字节一致的, git 里不会出现虚假改动。
    newest = next((i["date"] for i in items if i.get("date")), None)
    build_stamp = rfc822(newest) if newest else rfc822(datetime.now(TZ))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "  <channel>",
        f"    <title>{esc(src['title'])}</title>",
        f"    <link>{esc(src.get('site') or src.get('page') or src.get('url', ''))}</link>",
        f"    <description>{esc(src.get('desc', ''))}</description>",
        "    <language>zh-cn</language>",
        f"    <lastBuildDate>{build_stamp}</lastBuildDate>",
    ]
    if newest:
        lines.append(f"    <pubDate>{rfc822(newest)}</pubDate>")
    lines += [
        "    <generator>energy-rss</generator>",
        "    <ttl>60</ttl>",
        f'    <atom:link href="{esc(self_url)}" rel="self" type="application/rss+xml"/>',
    ]
    for it in items:
        lines.append("    <item>")
        lines.append(f"      <title>{esc(it['title'])}</title>")
        lines.append(f"      <link>{esc(it['link'])}</link>")
        lines.append(f'      <guid isPermaLink="false">{esc(it["guid"])}</guid>')
        if it.get("date"):
            lines.append(f"      <pubDate>{rfc822(it['date'])}</pubDate>")
        if it.get("author"):
            lines.append(f"      <dc:creator>{esc(it['author'])}</dc:creator>")
        lines.append(f"      <description>{cdata(it.get('summary') or it['title'])}</description>")
        lines.append("    </item>")
    lines += ["  </channel>", "</rss>", ""]
    return "\n".join(lines)


def group_entries(entries: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(e["group"], []).append(e)
    return groups


def build_opml(entries: list[dict], title: str) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        "  <head>",
        f"    <title>{esc(title)}</title>",
        "  </head>",
        "  <body>",
    ]
    for group, items in group_entries(entries).items():
        lines.append(f'    <outline text="{esc(group)}" title="{esc(group)}">')
        for e in items:
            lines.append(
                f'      <outline type="rss" text="{esc(e["title"])}" title="{esc(e["title"])}"'
                f' xmlUrl="{esc(e["feed_url"])}" htmlUrl="{esc(e["site"])}"/>'
            )
        lines.append("    </outline>")
    lines += ["  </body>", "</opml>", ""]
    return "\n".join(lines)


def _status_line(info: dict) -> str:
    if not info:
        return '<div class="st">还没有运行过</div>'
    bits = []
    latest = str(info.get("latest") or "").strip()
    if latest:
        bits.append("最新一条 " + latest)
    count = int(info.get("items") or 0)
    if count:
        bits.append(f"{count} 条")
    line = f'<div class="st">{" · ".join(bits) or "还没有抓到内容"}</div>'
    err = info.get("error") or ""
    if err:
        line += f'<div class="st bad">最近一次抓取失败: {html_mod.escape(err[:110])}</div>'
    return line


def build_index(entries: list[dict], base_url: str, status: dict | None = None) -> str:
    status = status or {}
    cards: list[str] = []
    for group, items in group_entries(entries).items():
        cards.append(f"<h2>{html_mod.escape(group)}</h2>")
        cards.append('<div class="grid">')
        for e in items:
            add_url = "https://www.inoreader.com/?add_feed=" + urllib.parse.quote(e["feed_url"], safe="")
            cards.append(
                '<div class="card">'
                f'<div class="t">{html_mod.escape(e["title"])}</div>'
                f'<div class="d">{html_mod.escape(e["desc"])}</div>'
                f'<code>{html_mod.escape(e["feed_url"])}</code>'
                f'{_status_line(status.get(e["id"], {}))}'
                '<div class="row">'
                f'<a class="btn primary" href="{html_mod.escape(add_url)}" target="_blank"'
                ' rel="noopener">在 Inoreader 订阅</a>'
                f'<a class="btn" href="{html_mod.escape(e["feed_url"])}" target="_blank"'
                ' rel="noopener">看 XML</a>'
                "</div></div>"
            )
        cards.append("</div>")

    warn = ""
    if base_url == PLACEHOLDER_BASE:
        warn = (
            '<p class="warn">当前是占位地址。把仓库推到 GitHub 并跑过一次 Actions 之后, '
            "这里的链接会自动换成你自己的地址。</p>"
        )

    style = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 40px 24px 80px; background: #0f1115; color: #e6e8ee;
         font: 15px/1.7 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
  .wrap { max-width: 1000px; margin: 0 auto; }
  h1 { font-size: 26px; margin: 0 0 6px; }
  .sub { color: #8b93a7; margin-bottom: 26px; }
  h2 { font-size: 14px; color: #7f8aa3; font-weight: 600; letter-spacing: .08em;
       margin: 34px 0 12px; text-transform: uppercase; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
  .card { background: #171a21; border: 1px solid #242a35; border-radius: 12px; padding: 16px 18px; }
  .t { font-weight: 600; margin-bottom: 6px; }
  .d { color: #9aa3b8; font-size: 13px; margin-bottom: 12px; }
  code { display: block; background: #0d0f13; border: 1px solid #222834; border-radius: 6px;
         padding: 8px 10px; font-size: 12px; color: #7fd4a8; overflow-wrap: anywhere;
         font-family: ui-monospace, Consolas, monospace; }
  .row { display: flex; gap: 8px; margin-top: 12px; }
  .btn { display: inline-block; padding: 7px 12px; border-radius: 8px; text-decoration: none;
         font-size: 13px; border: 1px solid #2c3444; color: #cfd6e6; }
  .btn.primary { background: #2f6bff; border-color: #2f6bff; color: #fff; }
  .btn:hover { opacity: .88; }
  .warn { background: #3a2a12; border: 1px solid #6b4a12; color: #ffd08a;
          padding: 12px 14px; border-radius: 10px; }
  .how { background: #14181f; border: 1px solid #242a35; border-radius: 12px;
         padding: 16px 20px; color: #b7bfd2; }
  .how b { color: #e6e8ee; }
  .st { color: #7f8aa3; font-size: 12px; margin-top: 9px; }
  .st.bad { color: #ffb05c; }
  a { color: #7fb2ff; }
"""

    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>能源电力 RSS 订阅中心</title>\n"
        f"<style>{style}</style>\n</head>\n<body>\n<div class=\"wrap\">\n"
        "<h1>能源电力 RSS 订阅中心</h1>\n"
        f'<div class="sub">共 {len(entries)} 个源 · GitHub Actions 定时抓取 · '
        "点按钮即可加入 Inoreader</div>\n"
        f"{warn}\n"
        '<div class="how"><b>最快的一次性导入:</b> 下载 '
        '<a href="subscribe.opml">subscribe.opml</a>, 在 Inoreader 里进 '
        "<b>设置 → 导入 → 从文件</b>, 一次把全部源加进去。</div>\n"
        + "\n".join(cards)
        + "\n</div>\n</body>\n</html>\n"
    )


# ==========================================================================
# 主流程
# ==========================================================================

def resolve_base_url() -> str:
    explicit = os.environ.get("FEED_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
    if repo and "/" in repo:
        repo_owner, name = repo.split("/", 1)
        owner = owner or repo_owner
        if name.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner}.github.io"
        return f"https://{owner}.github.io/{name}"
    return PLACEHOLDER_BASE


def existing_item_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return path.read_text(encoding="utf-8").count("<item>")
    except OSError:
        return 0


def previous_links(path: Path) -> dict[str, str]:
    """读上一次生成的 feed, 取出 guid -> link 的映射。

    知网给的文章链接每次请求都会换一个令牌, 直接写进去会导致文件每轮都变。
    对同一篇文章沿用上次的链接, 内容没变时生成结果就是逐字节一致的。
    """
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {}
    out: dict[str, str] = {}
    for node in root.iter("item"):
        guid = (node.findtext("guid") or "").strip()
        link = (node.findtext("link") or "").strip()
        if guid and link:
            out[guid] = link
    return out


def load_status() -> dict:
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_status(status: dict) -> None:
    try:
        STATUS_PATH.write_text(
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        print(f"  (状态文件写入失败, 不影响订阅源: {exc})")


def entry_for(src: dict, base_url: str) -> dict:
    return {
        "id": src["id"],
        "group": src["group"],
        "title": src["title"],
        "desc": src.get("desc", ""),
        "site": src.get("site") or src.get("page") or src.get("url", ""),
        "feed_url": f"{base_url}/feeds/{src['id']}.xml",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取能源电力站点并生成 RSS")
    ap.add_argument("--dry-run", action="store_true", help="只抓取并打印, 不写文件")
    ap.add_argument("--only", default="", help="只处理指定 id, 逗号分隔")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS, help="每个源最多保留多少条")
    args = ap.parse_args()

    wanted = {x.strip() for x in args.only.split(",") if x.strip()}
    base_url = resolve_base_url()
    if not args.dry_run:
        FEED_DIR.mkdir(parents=True, exist_ok=True)
        (DOCS / ".nojekyll").write_text("", encoding="utf-8", newline="\n")

    entries: list[dict] = []
    ok = 0
    failed: list[str] = []
    kept: list[str] = []
    prev_status = load_status()
    status: dict = dict(prev_status)

    def record(sid: str, src: dict, items: list[dict], err: str) -> None:
        """状态里只放"内容相关"的字段, 不放运行时间, 免得每次跑都产生改动。"""
        prev = prev_status.get(sid, {})
        latest = ""
        if items:
            newest = next((i["date"] for i in items if i.get("date")), None)
            if newest:
                latest = newest.strftime("%Y-%m-%d %H:%M")
        status[sid] = {
            "title": src["title"],
            "group": src["group"],
            "items": len(items) if items else int(prev.get("items") or 0),
            "latest": latest or str(prev.get("latest") or ""),
            "error": err,
        }

    for src in SOURCES:
        sid = src["id"]
        if wanted and sid not in wanted:
            continue
        parser = PARSERS.get(src["kind"])
        label = f"{src['title']} ({sid})"
        err = ""
        if parser is None:
            print(f"  [跳过] {label}: 未知 kind={src['kind']!r}")
            failed.append(sid)
            err = f"未知 kind={src['kind']!r}"
            record(sid, src, [], err)
            continue
        try:
            items, extra = parser(src, {})
            items = finalize(items, args.max_items)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            print(f"  [失败] {label}: {err}")
            items, extra = [], {}
            failed.append(sid)
        else:
            note = ""
            if src["kind"] == "bjx" and extra.get("hosts"):
                note = "  来源域: " + ",".join(extra["hosts"])
            print(f"  [成功] {label}: {len(items)} 条{note}")

        record(sid, src, items, err)

        if args.dry_run:
            for it in items[:3]:
                when = it["date"].strftime("%Y-%m-%d %H:%M") if it.get("date") else "无日期"
                print(f"           · {when}  {it['title'][:56]}")
            if items:
                ok += 1
            continue

        path = FEED_DIR / f"{sid}.xml"

        # 知网的链接带一次性令牌, 同一篇文章沿用上一轮的链接, 保持文件稳定
        if items and src["kind"] == "cnki":
            reuse = previous_links(path)
            for it in items:
                prev_link = reuse.get(it["guid"])
                if prev_link:
                    it["link"] = prev_link

        if not items:
            old = existing_item_count(path)
            if old:
                kept.append(f"{sid}(保留旧版 {old} 条)")
                print(f"           -> 保留上一次的 {old} 条, 不覆盖")
            else:
                print("           -> 没有数据, 也没有旧版可留")
            continue

        path.write_text(
            build_rss(src, items, f"{base_url}/feeds/{sid}.xml"),
            encoding="utf-8",
            newline="\n",
        )
        ok += 1
        entries.append(entry_for(src, base_url))

    if args.dry_run:
        print(f"\n预览完成: {ok} 个源有数据。")
        return 0 if ok else 1

    # 这次没抓到但磁盘上还有旧文件的源, 也要照常出现在索引和 OPML 里
    listed = {e["id"] for e in entries}
    for src in SOURCES:
        if wanted and src["id"] not in wanted:
            continue
        if src["id"] in listed:
            continue
        if existing_item_count(FEED_DIR / f"{src['id']}.xml"):
            entries.append(entry_for(src, base_url))

    order = {s["id"]: i for i, s in enumerate(SOURCES)}
    entries.sort(key=lambda e: order.get(e["id"], 999))

    if entries:
        (DOCS / "subscribe.opml").write_text(
            build_opml(entries, "能源电力订阅源"), encoding="utf-8", newline="\n"
        )
        (DOCS / "index.html").write_text(
            build_index(entries, base_url, status), encoding="utf-8", newline="\n"
        )
    save_status(status)

    print(f"\n完成: 成功 {ok} 个源, 订阅地址前缀 {base_url}")
    if kept:
        print("  保留旧版: " + ", ".join(kept))
    if failed:
        print("  失败: " + ", ".join(failed))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
