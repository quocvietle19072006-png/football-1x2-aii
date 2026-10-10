import math
import statistics
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(page_title="Sports Match Analyzer", page_icon="🎯", layout="wide")
BASE = "https://api.the-odds-api.com/v4"
API_KEY = st.secrets.get("THE_ODDS_API_KEY", "")

st.title("🎯 Sports Match Analyzer")
st.caption("Phân tích odds trước trận • Ước tính xác suất tham chiếu • Sàng lọc chênh lệch giá")

if not API_KEY:
    st.error("Chưa tìm thấy THE_ODDS_API_KEY trong Streamlit Secrets.")
    st.code('THE_ODDS_API_KEY = "YOUR_KEY_HERE"', language="toml")
    st.stop()

session = requests.Session()


def api(path, params=None):
    query = dict(params or {})
    query["apiKey"] = API_KEY
    try:
        response = session.get(BASE + path, params=query, timeout=20)
        if response.status_code == 401:
            return {"_error": "API key không hợp lệ hoặc chưa được kích hoạt."}, {}
        if response.status_code == 429:
            return {"_error": "Đã hết hạn mức requests của gói API."}, {}
        if response.status_code == 422:
            return {"_error": "API không hỗ trợ môn/thị trường/khu vực này trong gói hiện tại."}, {}
        response.raise_for_status()
        meta = {"remaining": response.headers.get("x-requests-remaining"), "used": response.headers.get("x-requests-used")}
        return response.json(), meta
    except requests.RequestException as exc:
        return {"_error": f"Không kết nối được API: {exc}"}, {}
    except ValueError:
        return {"_error": "API trả về dữ liệu không hợp lệ."}, {}


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def fmt_time(value):
    dt = parse_time(value)
    return dt.astimezone().strftime("%d/%m/%Y %H:%M %Z") if dt else str(value or "Chưa có giờ")


def safe_float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def line_label(market_key, name, point):
    if point is None:
        return str(name)
    if market_key == "totals":
        return f"{name} {point:g}"
    return f"{name} ({point:+g})"


def analyze_market(bookmakers, market_key):
    """Compare exact market lines; probability is market consensus, not an independent model."""
    grouped = {}
    for book in bookmakers or []:
        book_name = book.get("title") or book.get("key") or "Nhà cái"
        for market in book.get("markets", []) or []:
            if market.get("key") != market_key:
                continue
            valid = []
            for outcome in market.get("outcomes", []) or []:
                price = safe_float(outcome.get("price"))
                if price and price > 1:
                    point = safe_float(outcome.get("point"))
                    valid.append((outcome, price, point))
            if len(valid) < 2:
                continue
            # A bookmaker's opposing spread sides use +x/-x; pair only matching absolute lines.
            lines = {}
            for outcome, price, point in valid:
                line_id = abs(point) if market_key == "spreads" and point is not None else point
                lines.setdefault(line_id, []).append((outcome, price, point))
            for line_id, outcomes in lines.items():
                if len(outcomes) < 2:
                    continue
                total = sum(1 / item[1] for item in outcomes)
                if total <= 0:
                    continue
                for outcome, price, point in outcomes:
                    name = str(outcome.get("name") or "Không rõ")
                    # Exact signed point prevents comparing different sides/lines across books.
                    key = (name, point)
                    grouped.setdefault(key, []).append({
                        "prob": (1 / price) / total,
                        "odds": price,
                        "book": book_name,
                        "updated": market.get("last_update"),
                    })

    rows = []
    market_names = {"h2h": "Moneyline / 1X2", "spreads": "Handicap / Spread", "totals": "Tài / Xỉu"}
    for (name, point), values in grouped.items():
        # One quote per bookmaker per exact outcome/line.
        unique = {}
        for v in values:
            if v["book"] not in unique or v["odds"] > unique[v["book"]]["odds"]:
                unique[v["book"]] = v
        values = list(unique.values())
        if not values:
            continue
        probs = [v["prob"] for v in values]
        consensus = statistics.median(probs)
        spread = statistics.pstdev(probs) if len(probs) > 1 else 0.0
        best = max(values, key=lambda v: v["odds"])
        fair = 1 / consensus if consensus > 0 else math.inf
        edge = consensus * best["odds"] - 1
        breakeven = 1 / best["odds"]
        if len(values) < 3:
            status = "⚪ Chưa đủ nguồn so sánh"
        elif spread > 0.035:
            status = "⚪ Odds lệch nhau — cần kiểm tra"
        elif edge >= 0.05:
            status = "🟡 Chênh lệch đáng kiểm tra"
        elif edge >= 0.02:
            status = "🟡 Chênh lệch nhỏ"
        else:
            status = "⛔ Chưa thấy chênh lệch thuận lợi"
        rows.append({
            "market_key": market_key,
            "Market": market_names.get(market_key, market_key),
            "Lựa chọn": line_label(market_key, name, point),
            "Điểm kèo": point,
            "Xác suất tham chiếu thị trường": consensus,
            "Xác suất hòa vốn theo odds": breakeven,
            "Odds tốt nhất": best["odds"],
            "Fair odds tham chiếu": fair,
            "Chênh lệch giá ước tính": edge,
            "Độ phân tán": spread,
            "Số nhà cái": len(values),
            "Nhà cái tốt nhất": best["book"],
            "Cập nhật gần nhất": best.get("updated"),
            "Kết luận": status,
        })
    return rows


sports, _ = api("/sports", {"all": "true"})
if isinstance(sports, dict) and sports.get("_error"):
    st.error(sports["_error"])
    st.stop()
if not isinstance(sports, list) or not sports:
    st.warning("API không trả về danh sách môn/giải khả dụng.")
    st.stop()

active_sports = [x for x in sports if x.get("active", True)] or sports
labels = [f"{x.get('title', x.get('key', 'Môn'))} ({x.get('key', '')})" for x in active_sports]
sport = active_sports[st.selectbox("1. Chọn môn / giải", range(len(active_sports)), format_func=lambda i: labels[i])]
sport_key = sport.get("key")

c1, c2 = st.columns(2)
with c1:
    region = st.selectbox("Khu vực nhà cái", ["us", "uk", "eu", "au"], index=0)
with c2:
    markets = st.multiselect("Thị trường muốn phân tích", ["h2h", "spreads", "totals"], default=["h2h", "spreads", "totals"], format_func=lambda x: {"h2h":"Moneyline / 1X2", "spreads":"Handicap / Spread", "totals":"Tài / Xỉu"}[x])

st.info("Lưu ý quan trọng: The Odds API cung cấp lịch và odds, không tự cung cấp đầy đủ phong độ/thống kê để tạo mô hình độc lập cho mọi môn. Vì vậy xác suất dưới đây là xác suất tham chiếu suy ra từ odds đã loại biên, không được gọi là dự đoán AI độc lập.")
if not markets:
    st.warning("Hãy chọn ít nhất một thị trường.")
    st.stop()

if st.button("🔍 Phân tích các trận trước giờ thi đấu", type="primary", use_container_width=True):
    st.session_state["scan_requested"] = True

with st.spinner("Đang lấy lịch và odds từ The Odds API..."):
    events_data, meta = api(f"/sports/{sport_key}/odds", {"regions": region, "markets": ",".join(markets), "oddsFormat": "decimal", "dateFormat": "iso"})
if isinstance(events_data, dict) and events_data.get("_error"):
    st.error(events_data["_error"])
    st.info("Thử chọn ít market hơn, đổi khu vực nhà cái hoặc chọn môn/giải khác. Phạm vi dữ liệu phụ thuộc gói API.")
    st.stop()
if not isinstance(events_data, list):
    st.warning("Dữ liệu sự kiện không hợp lệ.")
    st.stop()

now = datetime.now(timezone.utc)
upcoming = [e for e in events_data if parse_time(e.get("commence_time")) and parse_time(e.get("commence_time")) > now]
st.caption(f"Sự kiện trước trận: {len(upcoming)} • Requests còn lại: {meta.get('remaining', 'API không cung cấp')}")
if not upcoming:
    st.warning("API hiện không trả về trận sắp diễn ra cho lựa chọn này.")
    st.stop()

upcoming.sort(key=lambda e: parse_time(e.get("commence_time")))
def event_label(e):
    return f"{e.get('home_team', 'Đội A')} vs {e.get('away_team', 'Đội B')} — {fmt_time(e.get('commence_time'))}"
idx = st.selectbox("2. Chọn trận đấu", range(len(upcoming)), format_func=lambda i: event_label(upcoming[i]))
event = upcoming[idx]
st.subheader(event_label(event))

rows = []
for market_key in markets:
    rows.extend(analyze_market(event.get("bookmakers", []), market_key))
if not rows:
    st.warning("Chưa có đủ odds hợp lệ cho market đã chọn ở trận này.")
    st.stop()

rows.sort(key=lambda r: r["Chênh lệch giá ước tính"], reverse=True)
shortlist = [r for r in rows if r["Số nhà cái"] >= 3 and r["Độ phân tán"] <= 0.035 and r["Chênh lệch giá ước tính"] >= 0.02]
st.subheader("🏆 Các lựa chọn đáng kiểm tra nhất")
if shortlist:
    for i, r in enumerate(shortlist[:3], start=1):
        with st.container(border=True):
            st.markdown(f"### #{i} · {r['Lựa chọn']}")
            st.caption(f"{r['Market']} · {r['Kết luận']}")
            a, b, c = st.columns(3)
            a.metric("Odds tốt nhất", f"{r['Odds tốt nhất']:.3f}")
            b.metric("Xác suất tham chiếu", f"{r['Xác suất tham chiếu thị trường']*100:.1f}%")
            c.metric("Chênh lệch giá", f"{r['Chênh lệch giá ước tính']*100:+.1f}%")
            st.write(f"**Fair odds tham chiếu:** {r['Fair odds tham chiếu']:.3f} · **Hòa vốn cần:** {r['Xác suất hòa vốn theo odds']*100:.1f}%")
            st.write(f"**Odds tốt nhất tại:** {r['Nhà cái tốt nhất']} · **Nguồn so sánh:** {r['Số nhà cái']} · **Độ phân tán:** {r['Độ phân tán']*100:.2f}%")
            st.caption("Đây là chênh lệch so với thị trường tham chiếu, không phải bằng chứng chắc chắn về lợi nhuận. Hãy xác minh đúng handicap/tổng và odds còn hiệu lực.")
else:
    st.info("Chưa có lựa chọn nào vượt tiêu chí sàng lọc. App sẽ không tự chọn kèo khi dữ liệu chưa đủ.")

st.subheader("📋 Bảng phân tích đầy đủ")
display = []
for r in rows:
    display.append({
        "Market": r["Market"], "Lựa chọn / đường kèo": r["Lựa chọn"],
        "Xác suất tham chiếu": f"{r['Xác suất tham chiếu thị trường']*100:.1f}%",
        "Xác suất hòa vốn": f"{r['Xác suất hòa vốn theo odds']*100:.1f}%",
        "Odds tốt nhất": round(r["Odds tốt nhất"], 3),
        "Fair odds tham chiếu": round(r["Fair odds tham chiếu"], 3),
        "Chênh lệch giá": f"{r['Chênh lệch giá ước tính']*100:+.1f}%",
        "Nhà cái tốt nhất": r["Nhà cái tốt nhất"], "Số nhà cái": r["Số nhà cái"],
        "Độ phân tán": f"{r['Độ phân tán']*100:.2f}%", "Kết luận": r["Kết luận"],
    })
st.dataframe(display, use_container_width=True, hide_index=True)
with st.expander("Cách đọc và giới hạn của phân tích"):
    st.markdown("""
- **Xác suất tham chiếu:** trung vị xác suất của các nhà cái sau khi loại biên trong từng bảng odds.
- **Xác suất hòa vốn:** `1 / odds`; đây là tỷ lệ thắng cần có để hòa vốn trước các điều kiện khác.
- **Chênh lệch giá ước tính:** `xác suất tham chiếu × odds tốt nhất − 1`. Đây chỉ là bộ lọc thị trường, không phải xác suất dự đoán độc lập.
- **Độ phân tán:** mức bất đồng giữa xác suất tham chiếu của các nhà cái; thấp không có nghĩa chắc thắng.
- App tách handicap và tổng điểm theo đường kèo để hạn chế so sánh nhầm.
- Để có mô hình dự đoán độc lập thực sự cần dữ liệu lịch sử/phong độ/chỉ số chuyên biệt theo từng môn và kiểm định bằng kết quả quá khứ. Không thể suy ra các dữ liệu đó chỉ từ odds hiện tại.
""")
