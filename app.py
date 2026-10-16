import os
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(page_title="Esports Predictor Free", page_icon="🎮", layout="wide")
st.title("🎮 Esports Predictor — bản miễn phí")
st.caption("VALORANT · LoL · CS2 | Lịch trận và các thị trường có dữ liệu thật từ KashRock Sandbox")

BASE = "https://kashrock.up.railway.app/v6/esports"
SPORTS = {"VALORANT": "valorant", "League of Legends": "lol", "Counter-Strike 2": "cs2"}


def api_key():
    try:
        return str(st.secrets.get("KASHROCK_API_KEY", "")).strip()
    except Exception:
        return os.getenv("KASHROCK_API_KEY", "").strip()


def request_json(path, params=None):
    key = api_key()
    if not key:
        raise RuntimeError('Thiếu KASHROCK_API_KEY trong Streamlit Cloud → Settings → Secrets.')
    r = requests.get(
        f"{BASE}/{path.lstrip('/')}",
        headers={"X-API-Key": key, "Accept": "application/json"},
        params=params or {}, timeout=25,
    )
    if r.status_code == 401:
        raise RuntimeError("KashRock trả 401: API key không hợp lệ hoặc chưa được thêm vào Secrets.")
    if r.status_code == 403:
        raise RuntimeError("KashRock trả 403: key hiện tại không có quyền endpoint này. Không thể vượt quyền gói API.")
    if r.status_code == 429:
        raise RuntimeError("Đã chạm giới hạn gọi API. Hãy đợi rồi tải lại.")
    r.raise_for_status()
    return r.json()


def records(data, preferred=()):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (*preferred, "data", "results", "matches", "props", "items", "events", "offers"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def first(d, *keys, default="—"):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            if isinstance(v, dict):
                return v.get("name") or v.get("title") or default
            return v
    return default


def team_name(v):
    if isinstance(v, dict):
        return str(v.get("name") or v.get("team_name") or "TBD")
    return str(v or "TBD")


def normalize_match(m):
    a = first(m, "team1", "team_a", "home_team", "opponent1", "team_home", default="TBD")
    b = first(m, "team2", "team_b", "away_team", "opponent2", "team_away", default="TBD")
    if a == "TBD":
        a = team_name((m.get("teams") or [{}])[0]) if isinstance(m.get("teams"), list) and m.get("teams") else "TBD"
    if b == "TBD":
        b = team_name((m.get("teams") or [{}, {}])[1]) if isinstance(m.get("teams"), list) and len(m.get("teams")) > 1 else "TBD"
    return {
        "Trận": f"{a} vs {b}", "Đội A": a, "Đội B": b,
        "Giải": first(m, "competition", "tournament", "league", "event_name"),
        "Giờ bắt đầu": first(m, "event_time", "begin_at", "start_time", "scheduled_at"),
        "Trạng thái": first(m, "status", default="upcoming"),
        "Thể thức": first(m, "format", "best_of", "match_type"),
        "ID": first(m, "kr_match_id", "match_id", "id", default=""),
        "raw": m,
    }


def fmt_time(v):
    if not v or v == "—":
        return "Chưa công bố"
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(v)


def normalize_prop(p):
    player = first(p, "player_name", "player", "athlete_name", default="")
    team = first(p, "team", "team_name", default="")
    opponent = first(p, "opponent", "opponent_name", default="")
    market = first(p, "stat_type", "market", "market_name", "prop_type", "name", default="Thị trường")
    line = first(p, "line", "line_value", "target", default="—")
    direction = first(p, "direction", "selection", "side", default="—")
    odds = first(p, "odds", "price", "decimal_odds", "american_odds", default="Không có")
    event = first(p, "event_time", "start_time", "begin_at", default="—")
    match = first(p, "match_name", "event_name", default="")
    probability = first(p, "model_probability", "probability", "win_probability", "p_over", default=None)
    return {
        "Trận": match or (f"{team} vs {opponent}" if team and opponent else "Chưa ghép được trận"),
        "Người chơi": player or "—", "Đội": team or "—", "Thị trường": str(market),
        "Mốc": line, "Lựa chọn": str(direction), "Odds thực tế": odds,
        "Giờ bắt đầu": fmt_time(event), "Xác suất từ API": probability,
        "raw": p,
    }


def fetch_matches(sport):
    data = request_json(f"{sport}/matches", {"status": "upcoming", "limit": 100})
    out = []
    for item in records(data, ("matches",)):
        if isinstance(item, dict):
            m = normalize_match(item)
            if m["Đội A"] != "TBD" or m["Đội B"] != "TBD":
                out.append(m)
    return out, data


def fetch_props(sport):
    data = request_json(f"{sport}/props", {"limit": 100})
    out = [normalize_prop(x) for x in records(data, ("props", "items", "offers")) if isinstance(x, dict)]
    return out, data

with st.sidebar:
    st.subheader("Cài đặt")
    game = st.selectbox("Chọn game", list(SPORTS.keys()))
    view = st.radio("Hiển thị", ["Trận sắp tới", "Thị trường / props thật"])
    load = st.button("🔄 Tải dữ liệu", type="primary", use_container_width=True)
    st.caption("Bản Sandbox miễn phí: tối đa 500 request/ngày. Odds nhà cái/consensus lines có thể bị giới hạn theo gói.")

sport = SPORTS[game]
cache_key = f"{sport}_{'matches' if view == 'Trận sắp tới' else 'props'}"
if load or cache_key not in st.session_state:
    try:
        with st.spinner("Đang tải dữ liệu thật từ KashRock..."):
            if view == "Trận sắp tới":
                data_rows, raw = fetch_matches(sport)
            else:
                data_rows, raw = fetch_props(sport)
        st.session_state[cache_key] = data_rows
        st.session_state[cache_key + "_raw"] = raw
        st.session_state.pop(cache_key + "_error", None)
    except Exception as e:
        st.session_state[cache_key] = []
        st.session_state[cache_key + "_error"] = str(e)

if st.session_state.get(cache_key + "_error"):
    st.error(st.session_state[cache_key + "_error"])

rows = st.session_state.get(cache_key, [])
if view == "Trận sắp tới":
    st.subheader(f"📅 Trận sắp tới — {game}")
    if rows:
        st.success(f"Đã nhận {len(rows)} trận từ API.")
        st.dataframe([{"Trận": x["Trận"], "Giải": x["Giải"], "Bắt đầu": fmt_time(x["Giờ bắt đầu"]), "Trạng thái": x["Trạng thái"], "Thể thức": x["Thể thức"]} for x in rows], use_container_width=True, hide_index=True)
        st.subheader("Phân tích trận")
        chosen = st.selectbox("Chọn trận", rows, format_func=lambda x: f"{x['Trận']} — {fmt_time(x['Giờ bắt đầu'])}")
        st.write(f"**Giải:** {chosen['Giải']} · **Thể thức:** {chosen['Thể thức']} · **Trạng thái:** {chosen['Trạng thái']}")
        st.info("Bản miễn phí không tự bịa xác suất thắng. Khi không có xác suất mô hình đã được kiểm định hoặc dữ liệu phong độ phù hợp, app chỉ hiển thị thông tin trận và thị trường thật mà API cung cấp.")
        st.caption("Để xem thị trường có dữ liệu thật, chọn ‘Thị trường / props thật’ ở thanh bên và tải dữ liệu.")
    else:
        st.info("API không trả về trận phù hợp lúc này. Thử tải lại sau hoặc kiểm tra quyền API/key.")
else:
    st.subheader(f"📊 Thị trường / props thật — {game}")
    if rows:
        st.success(f"Đã nhận {len(rows)} mục thị trường/props từ API.")
        # Do not invent missing odds or probabilities; show only values returned by the source.
        table = [{k: r[k] for k in ("Trận", "Người chơi", "Đội", "Thị trường", "Mốc", "Lựa chọn", "Odds thực tế", "Giờ bắt đầu", "Xác suất từ API")} for r in rows]
        st.dataframe(table, use_container_width=True, hide_index=True)
        available_markets = sorted({r["Thị trường"] for r in rows})
        selected_market = st.selectbox("Lọc thị trường", ["Tất cả", *available_markets])
        filtered = rows if selected_market == "Tất cả" else [r for r in rows if r["Thị trường"] == selected_market]
        st.write(f"Hiển thị {len(filtered)} mục.")
        for r in filtered[:30]:
            with st.expander(f"{r['Trận']} · {r['Thị trường']} · {r['Lựa chọn']} {r['Mốc']}"):
                st.write(f"- Người chơi: {r['Người chơi']} · Đội: {r['Đội']}")
                st.write(f"- Odds API trả về: {r['Odds thực tế']}")
                if r["Xác suất từ API"] is not None:
                    st.write(f"- Xác suất API trả về: {r['Xác suất từ API']}")
                else:
                    st.caption("API không cung cấp xác suất mô hình cho mục này; app không tự tạo xác suất.")
                st.json(r["raw"])
    else:
        st.info("Không có props trả về. Có thể hiện chưa có dữ liệu cho game này hoặc endpoint bị giới hạn bởi quyền API.")

with st.expander("Giới hạn và nguồn dữ liệu"):
    st.markdown(
        "- Nguồn: KashRock API; app không tạo odds nhà cái giả.\n"
        "- Sandbox có thể cung cấp lịch trận và player props, nhưng không đảm bảo có mọi loại kèo thắng trận/map/tổng round.\n"
        "- Odds nhà cái và consensus lines có thể yêu cầu gói trả phí. Nếu API trả 403, app sẽ báo rõ thay vì hiển thị dữ liệu giả.\n"
        "- Chỉ nên coi là thông tin tham khảo; không có mô hình nào đảm bảo thắng cược."
    )
with st.expander("Cấu hình API key"):
    st.code('KASHROCK_API_KEY = "API_KEY_CUA_BAN"', language="toml")
    st.caption("Streamlit Cloud → App → Settings → Secrets. Không đưa API key lên GitHub hoặc chat.")
