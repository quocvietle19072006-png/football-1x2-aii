import math
import statistics
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import requests
import streamlit as st

st.set_page_config(page_title="Multi-Sport Bet Analyzer", page_icon="🎯", layout="wide")
ODDS_BASE = "https://api.the-odds-api.com/v4"
FOOTBALL_BASE = "https://v3.football.api-sports.io"
ODDS_KEY = st.secrets.get("THE_ODDS_API_KEY", "")
FOOTBALL_KEY = st.secrets.get("API_FOOTBALL_KEY", st.secrets.get("APISPORTS_KEY", ""))

st.title("🎯 Multi-Sport Bet Analyzer")
st.caption("Sàng lọc kèo trước trận • Xếp hạng lựa chọn • Tách rõ mô hình thống kê và tham chiếu thị trường")

if not ODDS_KEY:
    st.error("Thiếu THE_ODDS_API_KEY trong Streamlit Secrets.")
    st.code('THE_ODDS_API_KEY = "YOUR_KEY_HERE"', language="toml")
    st.stop()

session = requests.Session()
session.headers.update({"User-Agent": "MultiSportBetAnalyzer/2.0"})


def get_odds(path, params=None):
    p = dict(params or {})
    p["apiKey"] = ODDS_KEY
    try:
        r = session.get(ODDS_BASE + path, params=p, timeout=25)
        if r.status_code == 401:
            return {"_error": "API key The Odds API không hợp lệ."}, {}
        if r.status_code == 429:
            return {"_error": "Đã hết hạn mức The Odds API."}, {}
        if r.status_code == 422:
            return {"_error": "Môn/kèo/khu vực này không được gói API hỗ trợ."}, {}
        r.raise_for_status()
        return r.json(), {
            "remaining": r.headers.get("x-requests-remaining"),
            "used": r.headers.get("x-requests-used"),
            "last": r.headers.get("x-requests-last"),
        }
    except requests.RequestException as e:
        return {"_error": f"Lỗi kết nối The Odds API: {e}"}, {}
    except ValueError:
        return {"_error": "The Odds API trả về dữ liệu không hợp lệ."}, {}


def get_football(path, params=None):
    if not FOOTBALL_KEY:
        return None, "Chưa cấu hình API_FOOTBALL_KEY (tùy chọn)."
    try:
        r = session.get(
            FOOTBALL_BASE + path,
            params=params or {},
            headers={"x-apisports-key": FOOTBALL_KEY},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            return None, f"API-Football báo lỗi: {data['errors']}"
        return data.get("response", []), None
    except requests.RequestException as e:
        return None, f"Không lấy được dữ liệu API-Football: {e}"
    except ValueError:
        return None, "API-Football trả về dữ liệu không hợp lệ."


def dt_parse(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def local_time(v):
    d = dt_parse(v)
    return d.astimezone().strftime("%d/%m %H:%M %Z") if d else str(v or "Chưa rõ giờ")


def number(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def market_label(key):
    return {
        "h2h": "Thắng trận / 1X2",
        "h2h_3_way": "1X2 có hòa",
        "spreads": "Chấp điểm / handicap",
        "totals": "Tài / Xỉu",
        "btts": "Hai đội ghi bàn (BTTS)",
        "draw_no_bet": "Hòa được hoàn tiền (DNB)",
        "team_totals": "Tổng điểm/bàn của đội",
        "alternate_spreads": "Handicap thay thế",
        "alternate_totals": "Tài/Xỉu thay thế",
        "outrights": "Vô địch / outright",
    }.get(key, key)


def outcome_label(market_key, outcome):
    name = str(outcome.get("name") or "Lựa chọn")
    desc = outcome.get("description")
    point = number(outcome.get("point"))
    if desc:
        name = f"{desc}: {name}"
    if point is not None:
        if market_key in ("totals", "alternate_totals", "team_totals"):
            name = f"{name} {point:g}"
        else:
            name = f"{name} ({point:+g})"
    return name


def build_rows(bookmakers, market_key):
    """Vig-removed per-book probabilities, exact-line consensus, best available price."""
    grouped = {}
    for book in bookmakers or []:
        book_name = book.get("title") or book.get("key") or "Nhà cái"
        for market in book.get("markets", []) or []:
            if market.get("key") != market_key:
                continue
            outcomes = []
            for out in market.get("outcomes", []) or []:
                price = number(out.get("price"))
                if price is not None and price > 1:
                    point = number(out.get("point"))
                    outcomes.append((out, price, point))
            if len(outcomes) < 2:
                continue
            # Normalize only outcomes sharing the same line; spreads use absolute point for pairing.
            by_line = {}
            for out, price, point in outcomes:
                if market_key in ("spreads", "alternate_spreads") and point is not None:
                    line = abs(point)
                else:
                    line = point
                by_line.setdefault(line, []).append((out, price, point))
            for line, items in by_line.items():
                if len(items) < 2:
                    continue
                total = sum(1 / item[1] for item in items)
                if total <= 0:
                    continue
                for out, price, point in items:
                    name = outcome_label(market_key, out)
                    # Preserve outcome name and point to prevent mixing opposing sides/lines.
                    key = (name, number(point))
                    grouped.setdefault(key, []).append({
                        "p": (1 / price) / total,
                        "odds": price,
                        "book": book_name,
                        "updated": market.get("last_update"),
                    })
    rows = []
    for (name, point), vals in grouped.items():
        unique = {}
        for v in vals:
            if v["book"] not in unique or v["odds"] > unique[v["book"]]["odds"]:
                unique[v["book"]] = v
        vals = list(unique.values())
        if not vals:
            continue
        ps = [v["p"] for v in vals]
        p_ref = statistics.median(ps)
        dispersion = statistics.pstdev(ps) if len(ps) > 1 else 0.0
        best = max(vals, key=lambda x: x["odds"])
        edge = p_ref * best["odds"] - 1
        p_be = 1 / best["odds"]
        n = len(vals)
        # Ranking is intentionally conservative and does not label market-derived estimates as independent.
        confidence = "Thấp"
        if n >= 5 and dispersion <= 0.02:
            confidence = "Vừa (đồng thuận nhà cái)"
        elif n >= 3 and dispersion <= 0.035:
            confidence = "Thấp–vừa (đồng thuận nhà cái)"
        if n < 3:
            reason = "Ít nguồn odds để đối chiếu"
        elif dispersion > 0.035:
            reason = "Nhà cái bất đồng đáng kể"
        elif edge >= 0.03:
            reason = "Giá tốt hơn tham chiếu thị trường; cần xác minh kèo/đường kèo"
        else:
            reason = "Chưa có chênh lệch giá rõ ràng"
        rows.append({
            "market_key": market_key,
            "market": market_label(market_key),
            "selection": name,
            "point": point,
            "p_market": p_ref,
            "p_be": p_be,
            "best_odds": best["odds"],
            "fair_odds": 1 / p_ref if p_ref > 0 else math.inf,
            "edge": edge,
            "dispersion": dispersion,
            "books": n,
            "best_book": best["book"],
            "updated": best.get("updated"),
            "confidence": confidence,
            "reason": reason,
        })
    return rows


def team_match_score(a, b):
    a, b = (a or "").lower(), (b or "").lower()
    return max(SequenceMatcher(None, a, b).ratio(), SequenceMatcher(None, a.replace("fc", "").strip(), b.replace("fc", "").strip()).ratio())


@st.cache_data(ttl=900, show_spinner=False)
def football_prediction_for_match(home, away, kickoff_iso):
    """Optional independent-ish football input from API-Football's form/H2H model."""
    kickoff = dt_parse(kickoff_iso)
    if kickoff is None:
        return None, "Không đọc được thời gian trận."
    fixtures, err = get_football("/fixtures", {"date": kickoff.strftime("%Y-%m-%d"), "timezone": "UTC"})
    if err:
        return None, err
    best, best_score = None, 0.0
    for f in fixtures or []:
        teams = f.get("teams", {})
        h = teams.get("home", {}).get("name", "")
        a = teams.get("away", {}).get("name", "")
        score = (team_match_score(home, h) + team_match_score(away, a)) / 2
        if score > best_score:
            best, best_score = f, score
    if not best or best_score < 0.68:
        return None, "Không ghép được trận tương ứng đủ tin cậy giữa hai nguồn dữ liệu."
    fixture_id = best.get("fixture", {}).get("id")
    predictions, err = get_football("/predictions", {"fixture": fixture_id})
    if err or not predictions:
        return None, err or "API-Football chưa có dự đoán cho trận này."
    p = predictions[0].get("predictions", {})
    percent = p.get("percent", {})
    def pct(key):
        raw = str(percent.get(key, "")).replace("%", "").strip()
        v = number(raw)
        return v / 100 if v is not None else None
    probs = {"home": pct("home"), "draw": pct("draw"), "away": pct("away")}
    if any(v is None for v in probs.values()) or sum(probs.values()) <= 0:
        return None, "API-Football không trả đủ phần trăm xác suất."
    total = sum(probs.values())
    probs = {k: v / total for k, v in probs.items()}
    return {
        "home": best.get("teams", {}).get("home", {}).get("name", home),
        "away": best.get("teams", {}).get("away", {}).get("name", away),
        "probs": probs,
        "winner": p.get("winner", {}).get("name", "Chưa rõ"),
        "advice": p.get("advice", ""),
        "goals": p.get("goals", {}),
        "match_score": best_score,
    }, None


sports_data, _ = get_odds("/sports", {"all": "true"})
if isinstance(sports_data, dict) and sports_data.get("_error"):
    st.error(sports_data["_error"])
    st.stop()
if not isinstance(sports_data, list) or not sports_data:
    st.error("Không lấy được danh sách môn thể thao.")
    st.stop()

active = [s for s in sports_data if s.get("active", True)] or sports_data
labels = [f"{s.get('title', s.get('key', 'Môn'))} — {s.get('key', '')}" for s in active]
sport = active[st.selectbox("1. Chọn môn/giải", range(len(active)), format_func=lambda i: labels[i])]
sport_key = sport.get("key", "")
is_soccer = str(sport_key).startswith("soccer_")

regions = st.multiselect("Khu vực nhà cái", ["eu", "uk", "us", "au"], default=["eu", "uk"] if is_soccer else ["us"])
if not regions:
    st.warning("Chọn ít nhất một khu vực nhà cái.")
    st.stop()

base_markets = ["h2h", "spreads", "totals"]
if is_soccer:
    base_markets += ["h2h_3_way", "btts", "draw_no_bet", "team_totals"]
with st.expander("Thị trường bổ sung (chỉ có khi API và nhà cái hỗ trợ)"):
    extra_markets = st.multiselect(
        "Chọn thêm thị trường",
        ["alternate_spreads", "alternate_totals", "outrights"],
        default=[],
        format_func=market_label,
    )
markets = st.multiselect(
    "2. Thị trường phân tích",
    list(dict.fromkeys(base_markets + extra_markets)),
    default=["h2h"] + (["totals", "spreads"] if not is_soccer else ["h2h_3_way", "totals", "spreads", "btts"]),
    format_func=market_label,
)
st.caption("App chỉ hiện các thị trường có dữ liệu trả về. Phạm vi thực tế tùy gói The Odds API, giải đấu, khu vực và thời điểm.")

if st.button("🔍 Quét trận sắp diễn ra", type="primary", use_container_width=True):
    st.session_state["scan_requested"] = True
if not markets:
    st.warning("Chọn ít nhất một thị trường.")
    st.stop()

with st.spinner("Đang lấy lịch và odds..."):
    events, meta = get_odds(
        f"/sports/{sport_key}/odds",
        {"regions": ",".join(regions), "markets": ",".join(markets),
         "oddsFormat": "decimal", "dateFormat": "iso"},
    )
if isinstance(events, dict) and events.get("_error"):
    st.error(events["_error"])
    st.info("Thử giảm số thị trường/khu vực hoặc chọn môn khác. Không phải gói API nào cũng hỗ trợ mọi thị trường.")
    st.stop()
if not isinstance(events, list):
    st.error("Dữ liệu trận đấu không hợp lệ.")
    st.stop()

now = datetime.now(timezone.utc)
upcoming = [e for e in events if dt_parse(e.get("commence_time")) and dt_parse(e.get("commence_time")) > now]
upcoming.sort(key=lambda e: dt_parse(e.get("commence_time")))
st.caption(f"Trận chưa bắt đầu: {len(upcoming)} · API requests còn: {meta.get('remaining', 'không có thông tin')}")
if not upcoming:
    st.warning("Không có trận sắp diễn ra cho lựa chọn này. Hãy đổi giải hoặc thử lại sau.")
    st.stop()

def event_title(e):
    return f"{e.get('home_team', 'Đội A')} vs {e.get('away_team', 'Đội B')} · {local_time(e.get('commence_time'))}"

event_idx = st.selectbox("3. Chọn trận", range(len(upcoming)), format_func=lambda i: event_title(upcoming[i]))
event = upcoming[event_idx]
st.subheader(event_title(event))

rows = []
for m in markets:
    rows.extend(build_rows(event.get("bookmakers", []), m))
if not rows:
    st.warning("Trận này chưa có đủ odds cho thị trường đã chọn.")
    st.stop()

# Rank market-price candidates, but do not conflate this with a true predictive model.
rows.sort(key=lambda r: (r["edge"], r["books"], -r["dispersion"]), reverse=True)
shortlist = [
    r for r in rows
    if r["books"] >= 3 and r["dispersion"] <= 0.035 and r["edge"] >= 0.02
]
st.subheader("🏅 Xếp hạng kèo đáng kiểm tra")
st.info("Thứ hạng mặc định dựa trên giá tốt so với xác suất tham chiếu từ odds đã loại biên. Đây chưa phải mô hình xác suất độc lập cho mọi môn.")
if shortlist:
    for rank, r in enumerate(shortlist[:5], 1):
        with st.container(border=True):
            st.markdown(f"### #{rank} · {r['selection']}")
            st.caption(f"{r['market']} · Mức tin cậy dữ liệu: {r['confidence']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Odds tốt nhất", f"{r['best_odds']:.2f}")
            c2.metric("Xác suất tham chiếu", f"{r['p_market']*100:.1f}%")
            c3.metric("Chênh lệch giá", f"{r['edge']*100:+.1f}%")
            st.write(f"**Fair odds:** {r['fair_odds']:.2f} · **Xác suất hòa vốn:** {r['p_be']*100:.1f}%")
            st.write(f"**Nhà cái tốt nhất:** {r['best_book']} · **Nguồn so sánh:** {r['books']} · **Độ phân tán:** {r['dispersion']*100:.2f}%")
            st.write(f"**Lý do:** {r['reason']}.")
else:
    st.warning("Chưa có kèo vượt bộ lọc. Không có đề xuất cược khi dữ liệu/giá chưa đủ thuyết phục.")

if is_soccer and FOOTBALL_KEY:
    st.subheader("⚽ Kiểm tra dự đoán bóng đá từ dữ liệu phong độ")
    with st.spinner("Đang truy vấn API-Football để lấy dự đoán dựa trên phong độ/lịch sử..."):
        fp, ferr = football_prediction_for_match(
            event.get("home_team", ""), event.get("away_team", ""), event.get("commence_time", "")
        )
    if ferr:
        st.warning(f"Chưa có dự đoán thống kê riêng: {ferr}")
    else:
        st.caption("Nguồn mô hình ngoài: API-Football Predictions (dựa trên các đầu vào thống kê của nhà cung cấp; không phải mô hình do app tự huấn luyện).")
        p = fp["probs"]
        a, b, c = st.columns(3)
        a.metric(f"{fp['home']} thắng", f"{p['home']*100:.1f}%")
        b.metric("Hòa", f"{p['draw']*100:.1f}%")
        c.metric(f"{fp['away']} thắng", f"{p['away']*100:.1f}%")
        st.write(f"**Đội được nhà cung cấp nghiêng về:** {fp['winner']}")
        if fp.get("advice"):
            st.write(f"**Nhận định nhà cung cấp:** {fp['advice']}")
        if fp.get("goals"):
            st.write(f"**Dự đoán bàn thắng:** {fp['goals']}")
        st.caption(f"Độ khớp tên trận giữa hai nguồn: {fp['match_score']*100:.0f}%. Hãy xác nhận đúng trận trước khi tham khảo.")

st.subheader("📊 Tất cả lựa chọn")
display = []
for r in rows:
    display.append({
        "Thị trường": r["market"],
        "Lựa chọn": r["selection"],
        "Xác suất tham chiếu": f"{r['p_market']*100:.1f}%",
        "Hòa vốn": f"{r['p_be']*100:.1f}%",
        "Odds tốt nhất": round(r["best_odds"], 3),
        "Fair odds": round(r["fair_odds"], 3),
        "Chênh lệch giá": f"{r['edge']*100:+.1f}%",
        "Số nhà cái": r["books"],
        "Độ phân tán": f"{r['dispersion']*100:.2f}%",
        "Tin cậy dữ liệu": r["confidence"],
        "Nhà cái tốt nhất": r["best_book"],
    })
st.dataframe(display, use_container_width=True, hide_index=True)

with st.expander("Mô hình, độ tin cậy và giới hạn"):
    st.markdown("""
**1. Xác suất thị trường:** Với từng nhà cái, app loại biên bằng cách chuẩn hóa nghịch đảo odds trong cùng thị trường/đường kèo; sau đó lấy trung vị giữa các nhà cái.

**2. Chênh lệch giá:** `xác suất tham chiếu × odds tốt nhất − 1`. Đây là tín hiệu so sánh giá, không phải lợi nhuận đảm bảo. Giá trị dương có thể do khác biệt cập nhật, đường kèo không tương đương hoặc sai lệch dữ liệu.

**3. Mức tin cậy:** Chỉ phản ánh số nguồn odds và mức đồng thuận giữa nhà cái; không phải xác suất thắng.

**4. Dự đoán thống kê riêng:** Nếu có `API_FOOTBALL_KEY` trong Streamlit Secrets, app thử lấy dự đoán 1X2 từ API-Football cho bóng đá. Nguồn này không tự động cung cấp mô hình riêng cho mọi môn thể thao và mọi loại kèo.

**5. Để huấn luyện mô hình độc lập đúng nghĩa:** cần dữ liệu lịch sử có kết quả thật, thống kê chuyên môn theo môn/giải, quy trình backtest theo thời gian và đánh giá calibration, Brier score/log-loss, ROI sau biên nhà cái. Không được gọi odds hiện tại là AI dự đoán độc lập.

**6. Cược có rủi ro:** Không có kèo chắc thắng. Không tăng tiền để gỡ lỗ; chỉ dùng số tiền có thể mất.
""")
