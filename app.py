import os
import requests
import pandas as pd
import streamlit as st

BASE_URL = "https://oddiwire.com/v1"

st.set_page_config(page_title="Esports Odds Analyzer", page_icon="🎮", layout="wide")
st.title("🎮 Esports Odds Analyzer")
st.caption("CS2 • League of Legends • Dota 2 • Valorant • các game esports khác")

st.warning(
    "Ứng dụng này phân tích odds và xác suất do nhà cung cấp trả về; "
    "đây không phải mô hình AI độc lập đã được kiểm định và không bảo đảm kết quả."
)

def get_api_key():
    try:
        return st.secrets.get("ODDIWIRE_API_KEY", "")
    except Exception:
        return os.getenv("ODDIWIRE_API_KEY", "")

def fetch_fixtures(api_key, event_type, sport, limit):
    headers = {"x-api-key": api_key} if api_key else {}
    params = {"event_type": event_type, "limit": limit}
    if sport != "Tất cả":
        params["sport"] = sport
    response = requests.get(
        f"{BASE_URL}/fixtures",
        headers=headers,
        params=params,
        timeout=25,
    )
    if response.status_code == 401:
        raise RuntimeError("API key không hợp lệ hoặc chưa được gửi. Kiểm tra ODDIWIRE_API_KEY trong Streamlit Secrets.")
    if response.status_code == 429:
        raise RuntimeError("Đã vượt giới hạn request. Chờ theo thời gian nhà cung cấp trả về hoặc kiểm tra gói API.")
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "fixtures", "results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
        # Một số API trả object đơn lẻ
        if payload.get("id"):
            return [payload]
    return []

def normalize_fixture(f):
    competitors = f.get("competitors") or f.get("teams") or []
    team_names = []
    if isinstance(competitors, list):
        for team in competitors:
            if isinstance(team, dict):
                team_names.append(str(team.get("name") or team.get("team_name") or team.get("title") or ""))
            elif isinstance(team, str):
                team_names.append(team)
    markets = f.get("markets") or []
    rows = []
    for market in markets if isinstance(markets, list) else []:
        if not isinstance(market, dict):
            continue
        selections = market.get("selections") or []
        for sel in selections if isinstance(selections, list) else []:
            if not isinstance(sel, dict):
                continue
            price = sel.get("price")
            prob = sel.get("probability")
            try:
                price = float(price) if price is not None else None
            except (TypeError, ValueError):
                price = None
            try:
                prob = float(prob) * 100 if prob is not None else None
            except (TypeError, ValueError):
                prob = None
            rows.append({
                "Game": f.get("sport", ""),
                "Trạng thái": f.get("phase") or f.get("status") or "",
                "Giải đấu": (f.get("competition") or {}).get("name", "") if isinstance(f.get("competition"), dict) else str(f.get("competition", "")),
                "Trận đấu": " vs ".join([x for x in team_names if x]) or f.get("name", "Chưa rõ"),
                "Giờ thi đấu": f.get("start_time") or f.get("scheduled_at") or f.get("startTime") or "",
                "Thị trường": market.get("market") or market.get("canonical") or "",
                "Loại thị trường": market.get("canonical", ""),
                "Lựa chọn": sel.get("name") or sel.get("side") or sel.get("label") or "",
                "Mốc kèo": sel.get("line"),
                "Odds": price,
                "Xác suất nhà cung cấp (%)": round(prob, 2) if prob is not None else None,
                "Trạng thái kèo": market.get("status", ""),
            })
    return rows

with st.sidebar:
    st.header("Bộ lọc")
    event_type = st.radio("Loại trận", ["prematch", "live"], format_func=lambda x: "Sắp diễn ra" if x == "prematch" else "Đang live")
    sport = st.selectbox("Game", ["Tất cả", "CS2", "LOL", "DOTA2", "VALORANT", "R6", "KING_OF_GLORY", "EFOOTBALL", "EBASKETBALL"])
    limit = st.slider("Số trận tối đa", 10, 200, 50, step=10)
    use_demo = st.checkbox("Dùng khóa demo để thử (giới hạn)", value=False)

key = get_api_key()
if not key and use_demo:
    key = "demo"
elif not key:
    st.info(
        "Chưa tìm thấy API key. Bạn có thể bật “Dùng khóa demo để thử” ở thanh bên, "
        "hoặc thêm ODDIWIRE_API_KEY vào Streamlit → Settings → Secrets."
    )

if st.button("🔄 Tải dữ liệu", type="primary") or "fixtures_rows" not in st.session_state:
    if not key:
        st.stop()
    with st.spinner("Đang tải dữ liệu từ Oddiwire…"):
        try:
            fixtures = fetch_fixtures(key, event_type, sport, limit)
            rows = []
            for fixture in fixtures:
                rows.extend(normalize_fixture(fixture))
            st.session_state["fixtures_rows"] = rows
            st.session_state["fixtures_count"] = len(fixtures)
            st.session_state["last_error"] = ""
        except Exception as e:
            st.session_state["last_error"] = str(e)

if st.session_state.get("last_error"):
    st.error(st.session_state["last_error"])
elif "fixtures_rows" in st.session_state:
    rows = st.session_state["fixtures_rows"]
    st.metric("Số trận nhận được", st.session_state.get("fixtures_count", 0))
    if not rows:
        st.warning("API chưa trả về trận/kèo phù hợp với bộ lọc này. Thử chọn 'Tất cả', đổi loại trận hoặc kiểm tra quyền truy cập/gói API.")
    else:
        df = pd.DataFrame(rows)
        query = st.text_input("Tìm đội, giải đấu hoặc thị trường")
        if query:
            mask = df.astype(str).apply(lambda col: col.str.contains(query, case=False, na=False)).any(axis=1)
            df = df[mask]
        min_prob = st.slider("Lọc xác suất tối thiểu (%)", 0, 100, 0)
        if "Xác suất nhà cung cấp (%)" in df.columns:
            df = df[(df["Xác suất nhà cung cấp (%)"].isna()) | (df["Xác suất nhà cung cấp (%)"] >= min_prob)]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Tải bảng CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="esports_odds.csv",
            mime="text/csv",
        )
        st.caption("Xác suất là số do API cung cấp; không đồng nghĩa với xác suất thắng chắc chắn.")
