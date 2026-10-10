import math
import statistics
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(page_title="Sports Value Scanner", page_icon="🎯", layout="wide")
BASE = "https://api.the-odds-api.com/v4"
API_KEY = st.secrets.get("THE_ODDS_API_KEY", "")

st.title("🎯 Sports Value Scanner — The Odds API")
st.caption("Ưu tiên trước trận • So sánh odds cùng market/handicap • Sàng lọc chênh lệch giá")

if not API_KEY:
    st.error("Chưa tìm thấy THE_ODDS_API_KEY trong Streamlit Secrets.")
    st.code('THE_ODDS_API_KEY = "YOUR_KEY_HERE"', language="toml")
    st.stop()

session = requests.Session()


def api(path: str, params: dict | None = None):
    query = dict(params or {})
    query["apiKey"] = API_KEY
    try:
        response = session.get(BASE + path, params=query, timeout=20)
        if response.status_code == 401:
            return {"_error": "API key không hợp lệ hoặc chưa được kích hoạt."}, {}
        if response.status_code == 429:
            return {"_error": "Đã hết hạn mức requests của gói API."}, {}
        if response.status_code == 422:
            return {"_error": "Thể thao/thị trường này không được hỗ trợ trong gói hiện tại."}, {}
        response.raise_for_status()
        meta = {
            "remaining": response.headers.get("x-requests-remaining"),
            "used": response.headers.get("x-requests-used"),
        }
        return response.json(), meta
    except requests.RequestException as exc:
        return {"_error": f"Không kết nối được API: {exc}"}, {}
    except ValueError:
        return {"_error": "API trả về dữ liệu không đọc được."}, {}


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def fmt_time(value):
    dt = parse_time(value)
    if dt is None:
        return str(value or "Chưa có giờ")
    return dt.astimezone().strftime("%d/%m/%Y %H:%M %Z")


def line_key(outcome):
    """Include point/handicap in the identity so different lines are never merged."""
    point = outcome.get("point")
    try:
        point = round(float(point), 4) if point is not None else None
    except (TypeError, ValueError):
        point = str(point)
    return (str(outcome.get("name", "Không rõ")), point)


def market_probabilities(bookmakers, selected_market):
    # Compare only the same outcome AND the same line across bookmakers.
    grouped = {}
    for book in bookmakers or []:
        book_name = book.get("title") or book.get("key") or "Nhà cái"
        for market in book.get("markets", []) or []:
            if market.get("key") != selected_market:
                continue
            outcomes = market.get("outcomes", []) or []
            valid = [o for o in outcomes if isinstance(o.get("price"), (int, float)) and math.isfinite(o["price"]) and o["price"] > 1]
            # De-vig separately for each exact line. For spreads, opposing sides
            # normally carry +x/-x; abs(point) identifies the shared handicap line.
            by_line = {}
            for outcome in valid:
                name, point = line_key(outcome)
                if selected_market == "spreads":
                    line_id = abs(point) if isinstance(point, (int, float)) else point
                else:
                    line_id = point
                by_line.setdefault(line_id, []).append((outcome, name, point))
            for line_id, line_outcomes in by_line.items():
                if len(line_outcomes) < 2:
                    continue
                implied = [1 / float(item[0]["price"]) for item in line_outcomes]
                overround = sum(implied)
                if overround <= 0:
                    continue
                for (outcome, name, point), raw_prob in zip(line_outcomes, implied):
                    key = (name, point)
                    grouped.setdefault(key, []).append({
                        "p": raw_prob / overround,
                        "odds": float(outcome["price"]),
                        "book": book_name,
                        "market_last_update": market.get("last_update"),
                    })

    rows = []
    for (name, point), values in grouped.items():
        # Deduplicate a bookmaker if the API ever returns the same line more than once.
        by_book = {}
        for value in values:
            previous = by_book.get(value["book"])
            if previous is None or value["odds"] > previous["odds"]:
                by_book[value["book"]] = value
        values = list(by_book.values())
        if not values:
            continue

        probs = [v["p"] for v in values]
        dispersion = statistics.pstdev(probs) if len(probs) > 1 else 0.0
        market_prob = statistics.median(probs)
        best = max(values, key=lambda v: v["odds"])
        best_odds = best["odds"]
        fair_odds = 1 / market_prob if market_prob > 0 else math.inf
        edge = market_prob * best_odds - 1

        # Conservative labels: this is still market-based screening, not an independent model.
        if len(values) < 3:
            status = "⚪ CHƯA ĐỦ DỮ LIỆU"
        elif dispersion > 0.035:
            status = "⚪ ODDS CHÊNH LỆCH — KIỂM TRA"
        elif edge >= 0.05:
            status = "🟡 VALUE TIỀM NĂNG — KIỂM TRA"
        elif edge >= 0.02:
            status = "🟡 CÂN NHẮC"
        else:
            status = "⛔ CHƯA THẤY VALUE"

        market_label = {"h2h": "Moneyline / 1X2", "spreads": "Handicap / Spread", "totals": "Over / Under"}.get(selected_market, selected_market)
        choice = name
        if point is not None:
            if selected_market == "totals":
                choice = f"{name} {point:g}"
            else:
                choice = f"{name} ({point:+g})"
        rows.append({
            "Market": market_label,
            "Market key": selected_market,
            "Lựa chọn": choice,
            "Điểm chấp/tổng": point,
            "Xác suất thị trường": market_prob,
            "Odds tốt nhất": best_odds,
            "Edge ước tính": edge,
            "Fair odds": fair_odds,
            "Độ phân tán": dispersion,
            "Số nhà cái": len(values),
            "Trạng thái": status,
            "Nhà cái tốt nhất": best["book"],
        })
    return rows


sports_payload, _ = api("/sports", {"all": "true"})
if isinstance(sports_payload, dict) and sports_payload.get("_error"):
    st.error(sports_payload["_error"])
    st.stop()
if not isinstance(sports_payload, list) or not sports_payload:
    st.warning("API không trả về danh sách môn thể thao khả dụng.")
    st.stop()

active_sports = [s for s in sports_payload if s.get("active", True)] or sports_payload
sport_labels = [f"{s.get('title', s.get('key', 'Môn'))} ({s.get('key', '')})" for s in active_sports]
sport_idx = st.selectbox("Chọn môn / giải đấu", range(len(active_sports)), format_func=lambda i: sport_labels[i])
sport = active_sports[sport_idx]
sport_key = sport.get("key")

c1, c2, c3 = st.columns(3)
with c1:
    regions = st.selectbox("Khu vực nhà cái", ["us", "uk", "eu", "au"], index=0,
                           help="Odds phụ thuộc khu vực và phạm vi gói API.")
with c2:
    mode = st.selectbox("Loại sự kiện", ["Sắp diễn ra", "Live (nếu API có cung cấp)"])
with c3:
    markets = st.multiselect("Thị trường", ["h2h", "spreads", "totals"],
                             default=["h2h", "spreads", "totals"],
                             format_func=lambda x: {"h2h": "Moneyline / 1X2", "spreads": "Handicap / Spread", "totals": "Over / Under"}.get(x, x))

if not markets:
    st.info("Chọn ít nhất một thị trường.")
    st.stop()

with st.expander("Cách đọc kết quả"):
    st.write("Edge ở đây là chỉ báo so sánh odds với xác suất suy ra từ chính thị trường sau khi loại biên từng nhà cái. Nó không phải dự đoán độc lập và không đảm bảo lợi nhuận. Các đường handicap/tổng khác nhau được tách riêng.")

if st.button("🔄 Tải odds và phân tích", type="primary", use_container_width=True):
    st.session_state["run_scan"] = True

# Keep existing behavior of loading on page open; the button can be used to rerun manually.
with st.spinner("Đang tải sự kiện và odds..."):
    events_payload, odds_meta = api(
        f"/sports/{sport_key}/odds",
        {"regions": regions, "markets": ",".join(markets), "oddsFormat": "decimal", "dateFormat": "iso"},
    )

if isinstance(events_payload, dict) and events_payload.get("_error"):
    st.error(events_payload["_error"])
    st.info("Gói API có thể giới hạn môn, market, khu vực hoặc live odds. Thử môn khác hay chọn ít market hơn.")
    st.stop()
if not isinstance(events_payload, list):
    st.warning("API không trả về danh sách sự kiện hợp lệ.")
    st.stop()

now = datetime.now(timezone.utc)
def is_live(event):
    start = parse_time(event.get("commence_time"))
    return start is not None and start <= now

if mode.startswith("Live"):
    events = [e for e in events_payload if is_live(e)]
else:
    # Strictly upcoming events only; past and already-started events are excluded.
    events = [e for e in events_payload if (parse_time(e.get("commence_time")) is not None and parse_time(e.get("commence_time")) > now)]

st.caption(f"Sự kiện tìm thấy: {len(events)} • Requests còn lại: {odds_meta.get('remaining', 'API không trả header')}")
if not events:
    st.warning("Không có sự kiện phù hợp. Với chế độ trước trận, chỉ hiện sự kiện có giờ bắt đầu trong tương lai và odds được API trả về.")
    st.stop()

def event_label(event):
    return f"{event.get('home_team', 'Đội A')} vs {event.get('away_team', 'Đội B')} — {fmt_time(event.get('commence_time'))}"

idx = st.selectbox("Chọn sự kiện", range(len(events)), format_func=lambda i: event_label(events[i]))
event = events[idx]
st.subheader(event_label(event))

all_rows = []
for market_key in markets:
    all_rows.extend(market_probabilities(event.get("bookmakers", []), market_key))

if not all_rows:
    st.warning("Sự kiện này chưa có odds hợp lệ cho market đã chọn.")
    st.stop()

# A recommendation requires several bookmakers and low enough disagreement.
ranked = sorted(all_rows, key=lambda r: r["Edge ước tính"], reverse=True)
positive = [r for r in ranked if r["Edge ước tính"] >= 0.02 and r["Số nhà cái"] >= 3 and r["Độ phân tán"] <= 0.035]

st.subheader("🔥 Kèo có chênh lệch giá đáng kiểm tra")
if positive:
    for row in positive[:3]:
        with st.container(border=True):
            st.markdown(f"### {row['Lựa chọn']}")
            st.caption(f"{row['Trạng thái']} • {row['Market']}")
            a, b, c = st.columns(3)
            a.metric("Edge ước tính", f"{row['Edge ước tính'] * 100:+.1f}%")
            b.metric("Odds tốt nhất", f"{row['Odds tốt nhất']:.3f}")
            c.metric("Fair odds", f"{row['Fair odds']:.3f}")
            st.write(f"**Xác suất thị trường:** {row['Xác suất thị trường'] * 100:.1f}%  ·  **Nhà cái:** {row['Nhà cái tốt nhất']}  ·  **Số nhà cái:** {row['Số nhà cái']}")
    st.warning("Các mục trên chỉ là chênh lệch giá tiềm năng dựa trên odds thị trường, không phải khuyến nghị chắc thắng. Kiểm tra lại đường chấp/tổng, thời điểm cập nhật và điều kiện cược tại nhà cái.")
else:
    st.info("Chưa có lựa chọn nào vượt ngưỡng sàng lọc với đủ số nhà cái và mức phân tán phù hợp. Không ép đưa ra kèo.")

st.subheader("📊 Tất cả market API trả về")
display = []
for row in ranked:
    display.append({
        "Market": row["Market"],
        "Lựa chọn / đường kèo": row["Lựa chọn"],
        "Xác suất thị trường": f"{row['Xác suất thị trường'] * 100:.1f}%",
        "Odds tốt nhất": round(row["Odds tốt nhất"], 3),
        "Fair odds": round(row["Fair odds"], 3),
        "Edge ước tính": f"{row['Edge ước tính'] * 100:+.1f}%",
        "Nhà cái tốt nhất": row["Nhà cái tốt nhất"],
        "Số nhà cái": row["Số nhà cái"],
        "Độ phân tán": f"{row['Độ phân tán'] * 100:.2f}%",
        "Trạng thái": row["Trạng thái"],
    })
st.dataframe(display, use_container_width=True, hide_index=True)
st.caption("Lưu ý: The Odds API không bao phủ mọi môn/esports hay mọi market trong mọi gói. App này chưa có mô hình dự đoán độc lập; Edge là phép sàng lọc dựa trên giá thị trường và không đảm bảo thắng.")
