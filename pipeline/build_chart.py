#!/usr/bin/env python3
"""
경제 지표 차트를 브랜드 톤으로 렌더링한다.

야후파이낸스·인베스팅닷컴 화면을 그대로 캡처하면 저작권 문제도 생기고
채널 톤도 깨진다. 숫자만 가져와서 우리 스타일로 다시 그린다.

spec 예시:
  {"kind": "line", "title": "원/달러 환율", "subtitle": "최근 5거래일", "unit": "원",
   "series": [{"label":"8.24","value":1381.0}, ...]}
"""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from generate_cards import esc, _inline_css

HERE = Path(__file__).parent
CARDS = HERE / "cards"

# 쇼츠 씬의 사진 슬롯 실제 크기와 맞춘다.
# (template_short.html의 .frame inset이 좌우 80px이므로 1080-160=920)
# 크기가 어긋나면 object-fit:cover가 축 라벨을 잘라먹는다.
W, H = 920, 820
PAD_L, PAD_R = 84, 64
PAD_T, PAD_B = 300, 130   # 위는 제목·수치, 아래는 x축 라벨


def _fmt(v: float) -> str:
    """1381.0 -> '1,381' / 3.005 -> '3.005' — 자릿수를 데이터에 맞춘다."""
    if abs(v) >= 1000 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _geometry(values, kind):
    lo, hi = min(values), max(values)
    span = (hi - lo) or (abs(hi) * 0.02 or 1.0)
    if kind == "bar":
        lo = min(0, lo)                     # 막대는 0에서 시작해야 왜곡이 없다
        span = (hi - lo) or 1.0
    else:
        lo -= span * 0.18                   # 선 그래프는 위아래 여백을 준다
        hi += span * 0.18
        span = hi - lo
    ix0, ix1 = PAD_L, W - PAD_R
    iy0, iy1 = PAD_T, H - PAD_B
    n = len(values)
    xs = [ix0 + (ix1 - ix0) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
    ys = [iy1 - (iy1 - iy0) * ((v - lo) / span) for v in values]
    return xs, ys, iy1


def _svg(spec, color, muted):
    kind = spec.get("kind", "line")
    series = spec["series"]
    values = [float(s["value"]) for s in series]
    xs, ys, base_y = _geometry(values, kind)

    parts = []
    # 배경 가로 기준선
    for f in (0.25, 0.5, 0.75):
        y = PAD_T + (H - PAD_B - PAD_T) * f
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                     f'stroke="{muted}" stroke-opacity="0.14" stroke-width="1.5"/>')

    if kind == "bar":
        n = len(values)
        slot = (W - PAD_R - PAD_L) / n
        bw = min(slot * 0.52, 110)
        for i, (v, y) in enumerate(zip(values, ys)):
            cx = PAD_L + slot * (i + 0.5)
            top, height = min(y, base_y), abs(base_y - y)
            last = i == n - 1
            parts.append(
                f'<rect x="{cx-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{height:.1f}" '
                f'rx="8" fill="{color}" fill-opacity="{1.0 if last else 0.42}"/>')
            parts.append(
                f'<text x="{cx:.1f}" y="{top-22:.1f}" text-anchor="middle" '
                f'fill="{color if last else muted}" font-size="30" font-weight="700" '
                f'font-family="IBM Plex Mono, monospace">{esc(_fmt(v))}</text>')
    else:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        parts.append(
            f'<polygon points="{xs[0]:.1f},{base_y:.1f} {pts} {xs[-1]:.1f},{base_y:.1f}" '
            f'fill="url(#g)" />')
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                     f'stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>')
        for i, (x, y) in enumerate(zip(xs, ys)):
            last = i == len(xs) - 1
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{11 if last else 7}" '
                         f'fill="{color if last else "#0e1420"}" stroke="{color}" stroke-width="4"/>')
        parts.append(
            f'<text x="{xs[-1]:.1f}" y="{ys[-1]-34:.1f}" text-anchor="end" fill="{color}" '
            f'font-size="34" font-weight="700" font-family="IBM Plex Mono, monospace">'
            f'{esc(_fmt(values[-1]))}</text>')

    # x축 라벨 — 개수가 많으면 건너뛰며 표시
    step = max(1, len(series) // 6)
    for i, s in enumerate(series):
        if i % step and i != len(series) - 1:
            continue
        x = xs[i] if kind != "bar" else PAD_L + (W - PAD_R - PAD_L) / len(series) * (i + 0.5)
        parts.append(f'<text x="{x:.1f}" y="{H-PAD_B+52:.1f}" text-anchor="middle" '
                     f'fill="{muted}" font-size="30" '
                     f'font-family="IBM Plex Mono, monospace">{esc(s["label"])}</text>')

    return (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.34"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0.02"/>'
            f'</linearGradient></defs>' + "".join(parts) + "</svg>")


def render_chart(spec: dict, out_path: Path, theme: str = "dark") -> Path:
    """차트 spec을 PNG로 렌더링하고 경로를 반환한다."""
    accent = spec.get("accent", "economy")
    color = {"dark": {"economy": "#e8a33d", "tech": "#2dd4bf"},
             "light": {"economy": "#c2790f", "tech": "#0e8f83"}}[theme][accent]
    muted = "#8b93a7" if theme == "dark" else "#6b7080"

    values = [float(s["value"]) for s in spec["series"]]
    first, last = values[0], values[-1]
    diff = last - first
    up = diff >= 0
    delta_color = color if up else ("#e8664a" if theme == "dark" else "#c0442c")
    arrow = "▲" if up else "▼"
    # 금리·확률·실업률처럼 값 자체가 %인 지표는 변화를 %p로 써야 맞다.
    # delta_mode="point"를 주면 퍼센트 변화율 대신 절대 변화만 표시한다.
    if spec.get("delta_mode") == "point":
        delta_text = f"{arrow} {_fmt(abs(diff))}%p"
    else:
        pct = (diff / first * 100) if first else 0
        delta_text = f"{arrow} {_fmt(abs(diff))} ({pct:+.2f}%)"

    css = _inline_css("@import url('_shared.css');", theme)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
{css}
html,body{{width:{W}px;height:{H}px;overflow:hidden;}}
body::after{{display:none;}}
.head{{position:absolute;left:{PAD_L}px;top:70px;}}
.t{{font-size:44px;font-weight:700;letter-spacing:-0.01em;}}
.s{{font-size:30px;color:var(--muted);margin-top:10px;font-family:'IBM Plex Mono',monospace;}}
.v{{font-family:'IBM Plex Mono',monospace;font-size:92px;font-weight:600;
   margin-top:22px;letter-spacing:-0.02em;line-height:1;}}
.d{{font-family:'IBM Plex Mono',monospace;font-size:36px;font-weight:600;
   margin-top:14px;color:{delta_color};}}
svg{{position:absolute;left:0;top:0;}}
</style></head><body>
{_svg(spec, color, muted)}
<div class="head">
  <div class="t">{esc(spec['title'])}</div>
  <div class="s">{esc(spec.get('subtitle',''))}</div>
  <div class="v">{esc(_fmt(last))}<span style="font-size:44px;color:var(--muted);"> {esc(spec.get('unit',''))}</span></div>
  <div class="d">{esc(delta_text)}</div>
</div></body></html>"""

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.parent / f"_tmp_{out_path.stem}.html"
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto(f"file://{tmp.resolve()}")
        pg.evaluate("() => document.fonts.ready")
        pg.screenshot(path=str(out_path))
        b.close()
    tmp.unlink()
    return out_path


if __name__ == "__main__":
    import json, sys
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render_chart(spec, Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "chart.png"))
