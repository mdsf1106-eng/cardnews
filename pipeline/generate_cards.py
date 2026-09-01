#!/usr/bin/env python3
"""
news.json -> 카드뉴스 PNG 세트 (1080x1350, 캐러셀 순서대로 01_, 02_, ...)
"""
import html
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
CARDS = HERE / "cards"

# 그리드 썸네일(정사각형 크롭) 안전 영역: 상하 135px씩 잘려나감 (1080x1350 -> 1080x1080 중앙크롭)
SAFE_TOP = 135
SAFE_BOTTOM = 1350 - 135

# 테마별 강조색 (차트 sparkline 등 SVG에 하드코딩되는 색)
THEME_COLORS = {
    "dark": {"chart": "#e8a33d", "chart_low": "#e8664a"},
    "light": {"chart": "#c2790f", "chart_low": "#c0442c"},
}

# 카드에 붙는 아이콘 라이브러리 (직접 그린 심플 벡터 아이콘 - 실제 사진/로고 대신 사용)
def _icon(name, color="currentColor"):
    paths = {
        "stocks": '<path d="M6 34 L16 22 L24 28 L38 12" stroke="{c}" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M30 12 H38 V20" stroke="{c}" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        "rate": '<circle cx="22" cy="22" r="15" stroke="{c}" stroke-width="3.2" fill="none"/><path d="M22 13 V22 L28 27" stroke="{c}" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        "chip": '<rect x="12" y="12" width="20" height="20" rx="3" stroke="{c}" stroke-width="3.2" fill="none"/><path d="M17 12 V6 M27 12 V6 M17 38 V32 M27 38 V32 M12 17 H6 M12 27 H6 M32 17 H38 M32 27 H38" stroke="{c}" stroke-width="3" stroke-linecap="round"/>',
        "earnings": '<rect x="8" y="10" width="28" height="24" rx="3" stroke="{c}" stroke-width="3.2" fill="none"/><path d="M14 27 L19 19 L24 23 L30 15" stroke="{c}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        "funding": '<path d="M22 8 V36 M15 14 c0-4 5-5 7-5 s7 1 7 5 -5 5 -7 5 -7 1 -7 5 5 5 7 5 7-1 7-5" stroke="{c}" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        "fx": '<circle cx="22" cy="22" r="15" stroke="{c}" stroke-width="3.2" fill="none"/><path d="M22 7 v30 M7 22 h30" stroke="{c}" stroke-width="2.4"/>',
        "realestate": '<path d="M8 22 L22 9 L36 22 M12 20 V36 H32 V20" stroke="{c}" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
        "jobs": '<rect x="8" y="15" width="28" height="19" rx="3" stroke="{c}" stroke-width="3.2" fill="none"/><path d="M16 15 v-4 a3 3 0 0 1 3-3 h6 a3 3 0 0 1 3 3 v4" stroke="{c}" stroke-width="3.2" fill="none"/>',
        "policy": '<path d="M22 8 L36 15 L22 22 L8 15 Z" stroke="{c}" stroke-width="3" fill="none" stroke-linejoin="round"/><path d="M13 19 V27 c0 3 5 5 9 5 s9 -2 9 -5 V19" stroke="{c}" stroke-width="3" fill="none" stroke-linecap="round"/>',
        "startup": '<path d="M22 6 c6 4 9 10 9 17 c0 4 -2 7 -2 7 l-4 -3 -3 3 -3 -3 -4 3 s-2 -3 -2 -7 c0 -7 3 -13 9 -17 Z" stroke="{c}" stroke-width="3" fill="none" stroke-linejoin="round"/><circle cx="22" cy="19" r="2.6" fill="{c}"/>',
        "power": '<path d="M25 5 L12 26 h9 l-3 13 L32 18 h-9 l3 -13 Z" stroke="{c}" stroke-width="3" fill="none" stroke-linejoin="round" stroke-linecap="round"/>',
        "default": '<circle cx="22" cy="22" r="3.4" fill="{c}"/><circle cx="22" cy="22" r="14" stroke="{c}" stroke-width="3" fill="none"/>',
    }
    body = paths.get(name, paths["default"]).format(c=color)
    return f'<svg width="44" height="44" viewBox="0 0 44 44" fill="none">{body}</svg>'


def esc(s):
    return html.escape(str(s), quote=False)


def rich(s, accent="economy"):
    """HTML-escape한 뒤 **키워드** 마크업을 강조 색상 span으로 변환."""
    s = esc(s)
    return re.sub(r"\*\*(.+?)\*\*", lambda m: f'<strong class="hl {accent}">{m.group(1)}</strong>', s)


def _inline_css(tpl: str, theme: str = "dark") -> str:
    css_file = "_shared_light.css" if theme == "light" else "_shared.css"
    css = (CARDS / css_file).read_text(encoding="utf-8")
    return tpl.replace("@import url('_shared.css');", css)


def _sparkline_path(points):
    """points: list of (x, y) in the 220x90 viewBox. 첫/끝 x는 0과 220이어야 함."""
    line = "M" + " L".join(f"{x},{y}" for x, y in points)
    fill = line + f" L220,90 L0,90 Z"
    return fill, line


def _photo_src(photo) -> str:
    """로컬 경로면 data URI로, URL이면 그대로. 렌더링 중 외부 로딩을 기다리지 않게 한다."""
    import base64, mimetypes
    src = str(photo)
    if src.startswith(("http://", "https://")):
        return src
    pth = Path(photo)
    if not pth.is_absolute():
        # news.json의 경로는 레포 루트 기준으로 적는다
        root = Path(__file__).resolve().parent.parent
        cand = root / photo
        if cand.exists():
            pth = cand
    mime = mimetypes.guess_type(pth.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(pth.read_bytes()).decode()


def build_cover_news(date_str, headline, subhead, handle, photo, kicker="오늘의 이슈",
                     credit=None, theme="dark", accent="economy"):
    """사진이 주인공인 뉴스형 표지. 헤드라인은 하단에 얹는다.

    photo는 로컬 경로 또는 URL. **자유 이용이 가능한 출처만 쓸 것** —
    미국 연방정부 저작물(퍼블릭 도메인), 위키미디어 커먼즈 CC, 공공누리 제1유형 등.
    언론사 보도사진은 안 된다.
    """
    tpl = _inline_css((CARDS / "template_cover_news.html").read_text(encoding="utf-8"), theme)
    tpl = tpl.replace("__PHOTO__", _photo_src(photo))
    tpl = tpl.replace("__DATE__", esc(date_str))
    tpl = tpl.replace("__KICKER__", esc(kicker))
    tpl = tpl.replace("__HEADLINE__", rich(headline, accent).replace("\n", "<br>"))
    tpl = tpl.replace("__SUBHEAD__", rich(subhead, accent))
    tpl = tpl.replace("__HANDLE__", esc(handle))
    tpl = tpl.replace("__CREDIT__", esc(credit or ""))
    return tpl


def build_cover(date_str, headline, subhead, count, handle, hot_tag="오늘의 헤드라인", chart=None,
                 theme="dark", accent="economy"):
    """
    chart(선택): {"label": "KOSPI · 8.26", "value": "6,742.74 ▲0.68%", "low": "-4.1%",
                  "points": [(0,32),(40,30),(75,78),(120,74),(160,26),(220,20)]}
    없으면 차트 없는 헤드라인 전용 표지로 렌더링.
    headline/subhead는 **키워드** 마크업으로 강조 가능.
    """
    tpl = _inline_css((CARDS / "template_cover.html").read_text(encoding="utf-8"), theme)
    tpl = tpl.replace("__DATE__", esc(date_str))
    tpl = tpl.replace("__HEADLINE__", rich(headline, accent).replace("\n", "<br>"))
    tpl = tpl.replace("__SUBHEAD__", rich(subhead, accent))
    tpl = tpl.replace("__HANDLE__", esc(handle))
    tpl = tpl.replace("__COUNT__", str(count))
    tpl = tpl.replace("오늘의 헤드라인", esc(hot_tag))

    colors = THEME_COLORS.get(theme, THEME_COLORS["dark"])
    tpl = tpl.replace("__CHART_COLOR__", colors["chart"])
    tpl = tpl.replace("__CHART_LOW_COLOR__", colors["chart_low"])

    if chart:
        points = chart["points"]
        fill_path, line_path = _sparkline_path(points)
        # SVG 좌표계는 y가 아래로 갈수록 커지므로, y값이 가장 큰 점이 차트상 저점이다.
        low_point = max(points, key=lambda p: p[1])
        tpl = tpl.replace("__CHART_PATH_FILL__", fill_path)
        tpl = tpl.replace("__CHART_PATH_LINE__", line_path)
        tpl = tpl.replace("__CHART_LOW_X__", str(low_point[0]))
        tpl = tpl.replace("__CHART_LOW_Y__", str(low_point[1]))
        tpl = tpl.replace("__CHART_END_Y__", str(points[-1][1]))
        tpl = tpl.replace("__CHART_LABEL__", esc(chart["label"]))
        tpl = tpl.replace("__CHART_VALUE__", esc(chart["value"]))
        # low_label이 있으면 그대로, 없으면 기존 스키마와 호환되게 "장중 {low}"
        low_text = chart.get("low_label") or f"장중 {chart['low']}"
        tpl = tpl.replace("__CHART_LOW__", esc(low_text))
    else:
        tpl = re.sub(r"<!--CHART_BLOCK_START-->.*?<!--CHART_BLOCK_END-->", "", tpl, flags=re.S)

    return tpl


def build_item(index, total, category, title, summary, source, handle,
               theme="dark", icon=None, sowhat=None, photo=None, photo_credit=None):
    """sowhat: '그래서 이게 무슨 뜻인지' 해석 한 줄.
    없으면 해석 블록을 통째로 제거한다(하위호환)."""
    catclass = "economy" if category == "경제" else "tech"
    catlabel = "경제·재테크" if category == "경제" else "IT·테크"
    icon_color = "#e8a33d" if (theme == "dark" and catclass == "economy") else \
                 "#5fc9c0" if (theme == "dark" and catclass == "tech") else \
                 "#c2790f" if catclass == "economy" else "#0e8f83"
    tpl = _inline_css((CARDS / "template_item.html").read_text(encoding="utf-8"), theme)
    tpl = tpl.replace("__INDEX__", f"{index:02d}")
    tpl = tpl.replace("__TOTAL__", f"{total:02d}")
    tpl = tpl.replace("__CATCLASS__", catclass)
    tpl = tpl.replace("__CATLABEL__", catlabel)
    tpl = tpl.replace("__TITLE__", rich(title, catclass))
    tpl = tpl.replace("__SUMMARY__", rich(summary, catclass))
    tpl = tpl.replace("__SOURCE__", esc(source))
    tpl = tpl.replace("__HANDLE__", esc(handle))
    tpl = tpl.replace("__ICON_SVG__", _icon(icon or "default", icon_color))
    if photo:
        tpl = tpl.replace("__BODYCLS__", "has-photo")
        tpl = tpl.replace("__PHOTO__", _photo_src(photo))
        if photo_credit:
            tpl = tpl.replace("__PCREDIT__", esc(photo_credit))
        else:
            tpl = re.sub(r"<!--PCREDIT_START-->.*?<!--PCREDIT_END-->", "", tpl, flags=re.S)
    else:
        tpl = tpl.replace("__BODYCLS__", "")
        tpl = re.sub(r"<!--PHOTO_START-->.*?<!--PHOTO_END-->", "", tpl, flags=re.S)
    if sowhat:
        tpl = tpl.replace("__SOWHAT__", rich(sowhat, catclass))
    else:
        tpl = re.sub(r"<!--SOWHAT_START-->.*?<!--SOWHAT_END-->", "", tpl, flags=re.S)
    return tpl


def build_hook(date_str, label, line, note, count, handle, theme="dark"):
    """2번 카드 = 두 번째 표지.
    캐러셀을 봤지만 넘기지 않은 사람에게 인스타는 2번 미디어부터 재노출한다.
    그래서 이 카드는 1번의 반복이 아니라 '다른 각도의 훅'이어야 한다."""
    tpl = _inline_css((CARDS / "template_hook.html").read_text(encoding="utf-8"), theme)
    tpl = tpl.replace("__DATE__", esc(date_str))
    tpl = tpl.replace("__HOOK_LABEL__", esc(label))
    tpl = tpl.replace("__HOOK_LINE__", rich(line, "economy").replace("\n", "<br>"))
    tpl = tpl.replace("__HOOK_NOTE__", rich(note, "economy"))
    tpl = tpl.replace("__COUNT__", str(count))
    tpl = tpl.replace("__HANDLE__", esc(handle))
    return tpl


def build_outro(date_str, handle, question=None, theme="dark"):
    tpl = _inline_css((CARDS / "template_outro.html").read_text(encoding="utf-8"), theme)
    tpl = tpl.replace("__DATE__", esc(date_str))
    tpl = tpl.replace("__HANDLE__", esc(handle))
    tpl = tpl.replace("__QUESTION__", rich(question or "오늘 이슈 중에 가장 눈에 띈 건 뭐였나요?", "economy"))
    return tpl


def _fit_block(page, block_sel, head_sel, top_limit, bottom_limit, min_size, max_size):
    """block_sel 요소가 [top_limit, bottom_limit] 안에 들어올 때까지
    head_sel의 font-size를 줄여가며 재측정한다.
    헤드라인 길이가 매일 달라져도 잘리지 않게 하는 안전장치."""
    size = max_size
    while size >= min_size:
        rect = page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " if(!el) return null; const r = el.getBoundingClientRect();"
            " return {top:r.top, bottom:r.bottom}; }", block_sel
        )
        if rect is None:
            return size
        if rect["top"] >= top_limit - 2 and rect["bottom"] <= bottom_limit + 2:
            return size
        size -= 4
        page.evaluate(
            "([sel,px]) => { const el = document.querySelector(sel);"
            " if(el) el.style.fontSize = px + 'px'; }", [head_sel, size]
        )
    return size


def generate(news: dict, out_dir: Path, handle: str) -> list[Path]:
    """news.json 스키마의 dict를 받아 PNG 파일 목록(게시 순서)을 반환한다.

    카드 순서: 표지 → 훅(2번째 표지) → 아이템 N장 → 마무리
    hook 키가 없으면 훅 카드는 건너뛴다(기존 news.json 하위호환).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    items = news["items"]
    hook = news.get("hook")
    total_cards = len(items) + 2 + (1 if hook else 0)
    if not (2 <= total_cards <= 10):
        raise ValueError(f"캐러셀은 2~10장이어야 합니다 (현재 {total_cards}장)")

    theme = news.get("theme", "dark")
    n_items = len(items)
    paths = []
    seq = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350})

        def shot(html_str, name, fit=None):
            tmp = out_dir / f"_tmp_{name}.html"
            tmp.write_text(html_str, encoding="utf-8")
            page.goto(f"file://{tmp.resolve()}")
            page.evaluate("() => document.fonts.ready")  # 웹폰트 로딩 완료 대기
            if fit:
                _fit_block(page, *fit)
            out_path = out_dir / f"{name}.png"
            page.screenshot(path=str(out_path))
            tmp.unlink()
            return out_path

        # 01 표지 — 그리드 썸네일로 정사각 중앙크롭되므로 안전영역(135~1215) 안에 맞춘다
        seq += 1
        cover_photo = news.get("cover_photo")
        if cover_photo:
            # 사진형 표지 — 자유 이용 가능한 출처만 (연방정부 PD, 커먼즈 CC, 공공누리)
            paths.append(shot(
                build_cover_news(
                    news["date"], news["headline"], news["subhead"], handle, cover_photo,
                    kicker=news.get("hot_tag", "오늘의 이슈"),
                    credit=news.get("cover_credit"), theme=theme,
                ),
                f"{seq:02d}_cover",
                fit=(".headline-zone", "h1", SAFE_TOP, SAFE_BOTTOM, 52, 74),
            ))
        else:
            paths.append(shot(
                build_cover(
                    news["date"], news["headline"], news["subhead"], n_items, handle,
                    hot_tag=news.get("hot_tag", "오늘의 헤드라인"),
                    chart=news.get("chart"),
                    theme=theme,
                ),
                f"{seq:02d}_cover",
                fit=(".title-block", "h1", SAFE_TOP, SAFE_BOTTOM, 60, 88),
            ))

        # 02 훅 — 그리드에 안 잡히므로 캔버스 전체(64~1286)를 쓴다
        if hook:
            seq += 1
            paths.append(shot(
                build_hook(
                    news["date"], hook.get("label", "그래서, 뭐가 달라지나"),
                    hook["line"], hook.get("note", ""), n_items, handle, theme=theme,
                ),
                f"{seq:02d}_hook",
                fit=(".hook-block", ".hook-statement h2", 64, 1286, 56, 88),
            ))

        for item in items:
            seq += 1
            paths.append(shot(
                build_item(seq, total_cards, item["category"], item["title"],
                           item["summary"], item["source"], handle, theme=theme,
                           icon=item.get("icon"), sowhat=item.get("sowhat"),
                           photo=item.get("photo"), photo_credit=item.get("photo_credit")),
                f"{seq:02d}_item",
            ))

        seq += 1
        paths.append(shot(
            build_outro(news["date"], handle, question=news.get("question"), theme=theme),
            f"{seq:02d}_outro",
        ))

        browser.close()

    return paths


if __name__ == "__main__":
    import sys
    news_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "news.example.json"
    config_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "config.example.json"
    news = json.loads(news_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out = generate(news, HERE / "out", config["account_handle"])
    print("generated:", [str(p) for p in out])
