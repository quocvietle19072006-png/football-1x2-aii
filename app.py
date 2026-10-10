import math
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st

# All-sport odds scanner and market-probability analyzer.
# Predictions derived from odds are market-implied estimates, not an independent model.
API_BASE = "https://api.the-odds-api.com/v4"
TIMEOUT = 25

st.set_page_config(page_title="All-Sport & Esports Odds Lab", page_icon="🎯", layout="wide")

st.title("🎯 All-Sport & Esports Odds Lab")
st.caption("Quét odds • xác suất thị trường đã loại biên • so sánh giá • lọc kèo")

st.warning(
    "Lưu ý: ứng dụng không thể bảo đảm thắng cược. Xác suất thị trường bên dưới được tính từ odds nhà cái "
    "(đã loại phần biên khi đủ dữ liệu), không phải xác suất dự đoán độc lập. "
    "Không tự tạo kèo khi API không trả dữ liệu."
)

def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()

api_key = get_secret("THE_ODDS_API_KEY")
with st.sidebar:
    st.header("Cài đặt")
    if not api_key:
        st.error("Chưa có THE_ODDS_API_KEY.")
        st.markdown(
            "Trong Streamlit → Manage app → Settings → Secrets, thêm:\n\n"
            "```toml\nTHE_ODDS_API_KEY = \"API_KEY_CUA_BAN\"\n```"
        )
    else:
        st.success("Đã tìm thấy cấu hình API key (không hiển thị key).")
    regions = st.selectbox("Khu vực nhà cái", ["us", "uk", "eu", "au", "us,uk,eu"], index=0)
    odds_format_label = st.selectbox("Định dạng odds", ["Decimal", "American"], index=0)
    odds_format = "decimal" if odds_format_label == "Decimal" else "american"
    include_live = st.checkbox("Hiển thị trận đang diễn ra nếu API trả về", value=True)
    market_choices = st.multiselect(
        "Thị trường cần tải",
        ["h2h", "spreads", "totals", "outrights"],
        default=["h2h", "spreads", "totals"],
        format_func=lambda x: {
            "h2h": "Moneyline / 1X2",
            "spreads": "Handicap / Spread",
            "totals": "Tài / Xỉu",
            "outrights": "Vô địch / Outright",
        }[x],
    )
    min_edge = st.slider("Ngưỡng chênh lệch so với xác suất thị trường (%)", 0, 15, 3)
    st.caption("Ngưỡng này chỉ sàng lọc chênh lệch giá giữa các nhà cái; không phải cam kết có lợi thế thật.")

def api_get(path: str, params: dict | None = None):
    if not api_key:
        raise RuntimeError("Thiếu THE_ODDS_API_KEY trong Streamlit Secrets.")
    p = dict(params or {})
    p["apiKey"] = api_key
    try:
        r = requests.get(f"{API_BASE}{path}", params=p, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"Không kết nối được API: {e}") from e
    if r.status_code == 401:
        raise RuntimeError("API key bị từ chối (401). Hãy kiểm tra key tại nhà cung cấp, không dán key vào chat.")
    if r.status_code == 403:
        raise RuntimeError("API key hợp lệ nhưng gói hiện tại không có quyền truy cập môn/thị trường này (403).")
    if r.status_code == 429:
        raise RuntimeError("Đã hết hạn mức request của API (429). Hãy chờ quota làm mới hoặc kiểm tra gói dịch vụ.")
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f"API trả lỗi HTTP {r.status_code}: {detail}")
    try:
        return r.json(), r.headers
    except ValueError as e:
        raise RuntimeError("API trả dữ liệu không phải JSON.") from e

@st.cache_data(ttl=900, show_spinner=False)
def load_sports(_key_marker: str):
    data, headers = api_get("/sports/", {})
    return data, {k: v for k, v in headers.items() if k.lower().startswith("x-requests-")}

@st.cache_data(ttl=90, show_spinner=False)
def load_odds(sport_key: str, regions: str, markets: str, odds_format: str, _key_marker: str):
    data, headers = api_get(f"/sports/{sport_key}/odds/", {
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
        "dateFormat": "iso",
    })
    return data, {k: v for k, v in headers.items() if k.lower().startswith("x-requests-")}

def decimal_odds(price: Any, fmt: str) -> float | None:
    try:
        p = float(price)
        if fmt == "decimal":
            return p if p > 1 else None
        if p > 0:
            return 1 + p / 100
        if p < 0:
            return 1 + 100 / abs(p)
    except (ValueError, TypeError, ZeroDivisionError):
        return None
    return None

def prob_from_price(price: Any, fmt: str) -> float | None:
    d = decimal_odds(price, fmt)
    return 1 / d if d and d > 1 else None

def build_rows(events: list[dict], fmt: str):
    rows = []
    for event in events:
        books = event.get("bookmakers") or []
        for market_key in sorted({m.get("key", "") for b in books for m in b.get("markets", [])}):
            market_entries = []
            for book in books:
                for market in book.get("markets", []):
                    if market.get("key") == market_key:
                        for outcome in market.get("outcomes", []):
                            price = outcome.get("price")
                            dec = decimal_odds(price, fmt)
                            implied = (1 / dec) if dec else None
                            market_entries.append({
                                "event": f"{event.get('home_team', event.get('name',''))} vs {event.get('away_team','')}".strip(" vs"),
                                "start": event.get("commence_time", ""),
                                "market_key": market_key,
                                "selection": outcome.get("name", ""),
                                "description": outcome.get("description", ""),
                                "point": outcome.get("point"),
                                "book": book.get("title", book.get("key", "")),
                                "odds": price,
                                "decimal": dec,
                                "implied": implied,
                                "event_id": event.get("id", ""),
                                "sport_key": event.get("sport_key", ""),
                            })
            # Approximate fair probabilities by removing overround within each bookmaker's market group.
            # Group by bookmaker and point to avoid mixing alternate lines.
            grouped: dict[tuple, list[int]] = {}
            for i, row in enumerate(market_entries):
                group_key = (row["book"], None if row["market_key"] == "spreads" else row["point"])
                grouped.setdefault(group_key, []).append(i)
            fair_by_row = {}
            for _, indexes in grouped.items():
                valid = [(i, market_entries[i]["implied"]) for i in indexes if market_entries[i]["implied"] is not None]
                total = sum(p for _, p in valid)
                if total > 0:
                    for i, p in valid:
                        fair_by_row[i] = p / total
            # Compare each selection's best available odds with median fair probability across books.
            selection_groups: dict[tuple, list[int]] = {}
            for i, row in enumerate(market_entries):
                selection_groups.setdefault((row["selection"], row["description"], row["point"]), []).append(i)
            for key, indexes in selection_groups.items():
                fair_vals = [fair_by_row[i] for i in indexes if i in fair_by_row]
                if not fair_vals:
                    continue
                fair = sum(fair_vals) / len(fair_vals)
                best_i = max((i for i in indexes if market_entries[i]["decimal"]), key=lambda i: market_entries[i]["decimal"], default=None)
                for i in indexes:
                    row = market_entries[i]
                    row["market_fair_prob"] = fair
                    row["best_decimal"] = market_entries[best_i]["decimal"] if best_i is not None else None
                    row["best_book"] = market_entries[best_i]["book"] if best_i is not None else ""
                    row["best_implied_prob"] = 1 / row["best_decimal"] if row["best_decimal"] else None
                    row["edge_pp"] = (fair - row["best_implied_prob"]) * 100 if row["best_implied_prob"] is not None else None
                    rows.append(row)
    return rows

if not api_key:
    st.info("Thêm THE_ODDS_API_KEY vào Secrets trước khi tải dữ liệu.")
    st.stop()

try:
    with st.spinner("Đang tải danh mục môn thể thao từ API..."):
        sports, quota = load_sports(api_key[-4:])
except Exception as e:
    st.error(str(e))
    st.markdown("Nếu key vừa được cập nhật, hãy vào **Manage app → ⋮ → Reboot app** rồi thử lại.")
    st.stop()

if not sports:
    st.warning("API không trả về danh mục môn thể thao. Kiểm tra gói API và key.")
    st.stop()

# Display all sports exposed by the current key, including esports if the subscription exposes them.
sports = sorted(sports, key=lambda s: (str(s.get("group", "")), str(s.get("title", ""))))
sport_groups: dict[str, list[dict]] = {}
for sport in sports:
    sport_groups.setdefault(sport.get("group", "Other"), []).append(sport)

st.subheader("Chọn môn / giải đấu")
group_names = list(sport_groups.keys())
group = st.selectbox("Nhóm môn", group_names)
group_sports = sport_groups[group]
sport_labels = [f"{s.get('title', s.get('key'))}  ({s.get('key')})" for s in group_sports]
chosen_label = st.selectbox("Môn / giải đấu", sport_labels)
sport = group_sports[sport_labels.index(chosen_label)]
sport_key = sport.get("key")

col1, col2, col3 = st.columns(3)
col1.metric("Môn/giải khả dụng với key", len(sports))
col2.metric("Nhóm môn", len(sport_groups))
col3.metric("Mã giải đang chọn", sport_key or "—")

if not market_choices:
    st.warning("Hãy chọn ít nhất một thị trường.")
    st.stop()

if st.button("🔄 Tải odds và phân tích", type="primary", use_container_width=True):
    st.session_state["run_scan"] = True

if st.session_state.get("run_scan"):
    try:
        with st.spinner(f"Đang tải odds cho {sport.get('title', sport_key)}..."):
            events, quota = load_odds(sport_key, regions, ",".join(market_choices), odds_format, api_key[-4:])
        if not events:
            st.warning(
                "API không trả trận/odds cho lựa chọn này. Có thể hiện không có trận, môn này chưa được gói hỗ trợ, "
                "hoặc sự kiện chưa mở thị trường. Thử giải khác hoặc giảm số market."
            )
            st.stop()
        rows = build_rows(events, odds_format)
        if not rows:
            st.warning("Có sự kiện nhưng chưa có odds phù hợp ở các thị trường đã chọn.")
            st.stop()
        df = pd.DataFrame(rows)
        df["start_display"] = pd.to_datetime(df["start"], errors="coerce", utc=True).dt.strftime("%d/%m/%Y %H:%M UTC")
        df["edge_pp"] = pd.to_numeric(df["edge_pp"], errors="coerce")
        df["market_fair_prob"] = pd.to_numeric(df["market_fair_prob"], errors="coerce")
        # Deduplicate to best price per event/market/selection/line, keeping all source context.
        dedup_keys = ["event_id", "market_key", "selection", "description", "point"]
        best_rows = df.sort_values("decimal", ascending=False).drop_duplicates(dedup_keys, keep="first").copy()
        best_rows["prob_pct"] = best_rows["market_fair_prob"] * 100
        best_rows["best_odds"] = best_rows["best_decimal"]
        best_rows["edge_label"] = best_rows["edge_pp"].map(lambda x: f"{x:+.2f} pp" if pd.notna(x) else "—")
        st.success(f"Đã tải {len(events)} sự kiện; tạo {len(best_rows)} lựa chọn có odds.")
        if quota:
            st.caption("Thông tin hạn mức API: " + " · ".join(f"{k}: {v}" for k, v in quota.items()))

        f1, f2 = st.columns(2)
        with f1:
            search = st.text_input("Tìm đội / người chơi / sự kiện", "")
        with f2:
            market_filter = st.multiselect(
                "Lọc thị trường",
                sorted(best_rows["market_key"].dropna().unique().tolist()),
                default=sorted(best_rows["market_key"].dropna().unique().tolist()),
            )
        filtered = best_rows.copy()
        if search.strip():
            filtered = filtered[filtered["event"].str.contains(search.strip(), case=False, na=False)]
        if market_filter:
            filtered = filtered[filtered["market_key"].isin(market_filter)]
        elif not market_filter:
            filtered = filtered.iloc[0:0]

        # Display best price and fair market estimate; do not imply independent prediction.
        display_cols = {
            "start_display": "Bắt đầu",
            "event": "Sự kiện",
            "market_key": "Market",
            "selection": "Lựa chọn",
            "description": "VĐV/đội (nếu có)",
            "point": "Line",
            "best_book": "Nhà cái tốt nhất",
            "best_odds": "Odds tốt nhất",
            "prob_pct": "Xác suất thị trường (%)",
            "edge_label": "Chênh lệch giá so với fair market",
        }
        st.subheader("Bảng phân tích")
        st.caption("Xác suất thị trường là trung bình các xác suất đã loại biên ở các nhà cái có dữ liệu tương ứng. Không phải xác suất độc lập.")
        st.dataframe(
            filtered[list(display_cols)].rename(columns=display_cols),
            use_container_width=True,
            hide_index=True,
        )

        shortlist = filtered[filtered["edge_pp"] >= min_edge].sort_values("edge_pp", ascending=False)
        st.subheader(f"Sàng lọc chênh lệch giá ≥ {min_edge} điểm phần trăm")
        if shortlist.empty:
            st.info("Chưa có lựa chọn đạt ngưỡng. Không ép ra kèo khi dữ liệu không đủ.")
        else:
            st.dataframe(
                shortlist[list(display_cols)].rename(columns=display_cols),
                use_container_width=True,
                hide_index=True,
            )
            st.caption("Chênh lệch có thể phản ánh khác biệt giữa nhà cái, thời điểm cập nhật hoặc cách định nghĩa market; cần kiểm tra thủ công trước khi ra quyết định.")

        csv = filtered.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Tải bảng phân tích CSV", csv, file_name="odds_analysis.csv", mime="text/csv")
        st.caption("Dữ liệu odds có thể thay đổi nhanh. Kiểm tra thời điểm cập nhật và luật thanh toán của nhà cái.")
    except Exception as e:
        st.error(str(e))
        st.markdown(
            "**Nếu lỗi API key:** kiểm tra `THE_ODDS_API_KEY` trong Streamlit Secrets. "
            "Nếu lỗi quyền truy cập, gói hiện tại có thể không hỗ trợ môn/market đã chọn. "
            "Không gửi key bí mật cho người khác."
        )

with st.expander("Các giới hạn quan trọng"):
    st.markdown(
        "- Danh mục hiển thị phụ thuộc hoàn toàn vào những môn mà API key/gói dịch vụ cho phép.\n"
        "- Gói miễn phí có thể chỉ hỗ trợ một số môn và market cơ bản; esports có thể cần gói riêng/cao hơn.\n"
        "- Ứng dụng hiện quét odds và tính xác suất ngầm định từ thị trường; không tuyên bố đây là mô hình dự đoán độc lập cho mọi môn.\n"
        "- Muốn mô hình độc lập cho từng môn (bóng đá, tennis, bóng rổ, CS2, LoL, Dota 2...), cần dữ liệu lịch sử phù hợp, đặc trưng riêng và backtest theo từng môn/market.\n"
        "- Không có hệ thống nào bảo đảm thắng hoặc có lợi nhuận."
    )
