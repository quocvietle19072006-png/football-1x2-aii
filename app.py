import os
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(page_title="Esports Kèo Predictor Free", page_icon="🎮", layout="wide")
st.title("🎮 Esports — Phân tích kèo miễn phí")
st.caption("VALORANT · League of Legends · CS2 | Chỉ dùng dữ liệu API thật; không tự bịa odds hoặc xác suất.")

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
        raise RuntimeError("Thiếu KASHROCK_API_KEY trong Streamlit Cloud → Settings → Secrets.")
    r = requests.get(f"{BASE}/{path.lstrip('/')}", headers={"X-API-Key": key, "Accept": "application/json"}, params=params or {}, timeout=25)
    if r.status_code == 401:
        raise RuntimeError("KashRock trả 401: kiểm tra API key trong Secrets.")
    if r.status_code == 403:
        raise RuntimeError("KashRock trả 403: gói/key không có quyền endpoint này. App không thể tự lấy dữ liệu bị khóa.")
    if r.status_code == 429:
        raise RuntimeError("Đã chạm giới hạn API. Hãy đợi rồi tải lại.")
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
    teams = m.get("teams") if isinstance(m.get("teams"), list) else []
    if a == "TBD" and teams:
        a = team_name(teams[0])
    if b == "TBD" and len(teams) > 1:
        b = team_name(teams[1])
    return {"Trận": f"{a} vs {b}", "Đội A": a, "Đội B": b,
            "Giải": first(m, "competition", "tournament", "league", "event_name"),
            "Giờ bắt đầu": first(m, "event_time", "begin_at", "start_time", "scheduled_at"),
            "Trạng thái": first(m, "status", default="upcoming"),
            "Thể thức": first(m, "format", "best_of", "match_type"),
            "ID": first(m, "kr_match_id", "match_id", "id", default=""), "raw": m}


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


def normalize_prob(value):
    try:
        p = float(value)
        if p > 1 and p <= 100:
            p /= 100
        return p if 0 < p < 1 else None
    except (TypeError, ValueError):
        return None


def decimal_odds(value, raw=None):
    # Only accept explicit decimal odds. Never guess odds format from absent data.
    candidates = [value]
    if isinstance(raw, dict):
        candidates += [raw.get(k) for k in ("decimal_odds", "odds_decimal", "price_decimal")]
    for v in candidates:
        try:
            if isinstance(v, str):
                v = v.strip().replace(",", ".")
            x = float(v)
            if 1.0 < x < 1000:
                return x
        except (TypeError, ValueError):
            continue
    return None


def normalize_prop(p):
    player = first(p, "player_name", "player", "athlete_name", default="")
    team = first(p, "team", "team_name", default="")
    opponent = first(p, "opponent", "opponent_name", default="")
    market = first(p, "stat_type", "market", "market_name", "prop_type", "name", default="Thị trường")
    line = first(p, "line", "line_value", "target", default="—")
    direction = first(p, "direction", "selection", "side", "outcome", default="—")
    odds_value = first(p, "decimal_odds", "odds_decimal", "price_decimal", "odds", "price", default=None)
    probability_value = first(p, "model_probability", "probability", "win_probability", "p_over", default=None)
    event = first(p, "event_time", "start_time", "begin_at", default="—")
    match = first(p, "match_name", "event_name", default="")
    probability = normalize_prob(probability_value)
    odds = decimal_odds(odds_value, p)
    ev = (probability * odds - 1) if probability is not None and odds is not None else None
    if probability is None or odds is None:
        recommendation = "Chưa đủ dữ liệu để đánh giá"
    elif ev > 0.03:
        recommendation = "Có thể nghiên cứu thêm (EV dương theo xác suất API)"
    else:
        recommendation = "Không ưu tiên / NO BET"
    return {"Trận": match or (f"{team} vs {opponent}" if team and opponent else "Chưa ghép được trận"),
            "Người chơi": player or "—", "Đội": team or "—", "Thị trường": str(market),
            "Mốc": line, "Lựa chọn": str(direction), "Odds thập phân thật": odds if odds is not None else "API không cung cấp",
            "Giờ bắt đầu": fmt_time(event), "Xác suất từ API": probability,
            "EV ước tính": ev, "Gợi ý": recommendation, "raw": p}


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
    game = st.radio("🎮 Chọn riêng từng game", list(SPORTS.keys()), key="selected_game")
    view = st.radio("Chức năng", ["Dự đoán kèo", "Trận sắp tới", "Thị trường / props thật"])
    load = st.button("🔄 Tải dữ liệu", type="primary", use_container_width=True)
    st.caption("Miễn phí: chỉ phân tích odds/xác suất nếu API thực sự trả về. Không tự tạo dữ liệu còn thiếu.")

st.subheader(f"🎮 Khu vực riêng: {game}")
st.caption("Dữ liệu lịch trận, thị trường và phân tích bên dưới chỉ áp dụng cho game đang chọn.")
sport = SPORTS[game]
view_to_endpoint = {"Dự đoán kèo": "props", "Thị trường / props thật": "props", "Trận sắp tới": "matches"}
endpoint = view_to_endpoint[view]
cache_key = f"{sport}_{endpoint}"
if load or cache_key not in st.session_state:
    try:
        with st.spinner("Đang tải dữ liệu từ KashRock..."):
            if endpoint == "matches":
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
        st.success(f"API trả về {len(rows)} trận.")
        st.dataframe([{"Trận": x["Trận"], "Giải": x["Giải"], "Bắt đầu": fmt_time(x["Giờ bắt đầu"]), "Trạng thái": x["Trạng thái"], "Thể thức": x["Thể thức"]} for x in rows], use_container_width=True, hide_index=True)
    else:
        st.info("API không trả về trận sắp tới cho game này. Hãy thử tải lại sau.")
elif view == "Thị trường / props thật":
    st.subheader(f"📊 Thị trường / props thật — {game}")
    if rows:
        st.success(f"API trả về {len(rows)} mục thị trường/props.")
        st.dataframe([{k: r[k] for k in ("Trận", "Người chơi", "Đội", "Thị trường", "Mốc", "Lựa chọn", "Odds thập phân thật", "Xác suất từ API")} for r in rows], use_container_width=True, hide_index=True)
        for r in rows[:30]:
            with st.expander(f"{r['Trận']} · {r['Thị trường']} · {r['Lựa chọn']} {r['Mốc']}"):
                st.write(f"**Odds:** {r['Odds thập phân thật']} · **Xác suất API:** {r['Xác suất từ API'] if r['Xác suất từ API'] is not None else 'Không có'}")
                st.json(r["raw"])
    else:
        st.info("API không trả về props cho game này, hoặc endpoint bị giới hạn bởi gói/key.")
else:
    st.subheader(f"🔮 Dự đoán và gợi ý kèo — {game}")
    st.write("App chỉ xếp hạng kèo khi có **cả odds thập phân thật và xác suất do API cung cấp**. Nếu thiếu một trong hai, app không tự đoán.")
    if rows:
        usable = [r for r in rows if r["EV ước tính"] is not None]
        if usable:
            ranked = sorted(usable, key=lambda r: r["EV ước tính"], reverse=True)
            positive = [r for r in ranked if r["EV ước tính"] > 0.03]
            if positive:
                st.success(f"Có {len(positive)} lựa chọn có EV ước tính trên 3% theo xác suất API. Đây không phải cam kết thắng.")
            else:
                st.warning("Chưa có lựa chọn nào vượt ngưỡng EV 3%. Gợi ý hiện tại: NO BET.")
            st.dataframe([{"Trận": r["Trận"], "Thị trường": r["Thị trường"], "Lựa chọn": r["Lựa chọn"], "Mốc": r["Mốc"], "Odds": r["Odds thập phân thật"], "Xác suất API": f"{r['Xác suất từ API']*100:.1f}%", "EV": f"{r['EV ước tính']*100:+.1f}%", "Gợi ý": r["Gợi ý"]} for r in ranked], use_container_width=True, hide_index=True)
            for r in ranked[:20]:
                with st.expander(f"{r['Gợi ý']} — {r['Trận']} / {r['Thị trường']}"):
                    st.write(f"Lựa chọn: **{r['Lựa chọn']} {r['Mốc']}** · Odds: **{r['Odds thập phân thật']}** · Xác suất API: **{r['Xác suất từ API']*100:.1f}%** · EV: **{r['EV ước tính']*100:+.1f}%**")
                    st.caption("EV = xác suất × odds thập phân − 1. Chỉ đáng tham khảo nếu xác suất API đã được kiểm định và cùng thị trường với odds.")
        else:
            st.warning("API có trả về mục thị trường, nhưng không có đủ cả odds thập phân và xác suất API để tính value. App không tự tạo dự đoán; hiện nên NO BET.")
        missing = len(rows) - len(usable)
        if missing:
            st.caption(f"{missing} mục bị loại khỏi xếp hạng vì thiếu odds hoặc xác suất.")
    else:
        st.info("Chưa có dữ liệu thị trường/props. Hãy thử tab ‘Thị trường / props thật’ hoặc tải lại sau; nếu API trả 403 thì gói miễn phí không có quyền endpoint đó.")

with st.expander("Nguồn dữ liệu và giới hạn"):
    st.markdown("- Nguồn: KashRock API, bằng API key do bạn cấu hình.\n- App chỉ đề xuất lựa chọn khi API cung cấp cả odds và xác suất.\n- Không suy ra kèo chấp, tổng map/round hay xác suất từ lịch trận đơn thuần.\n- EV dương không bảo đảm có lời; dữ liệu/API có thể thiếu hoặc không cùng thời điểm.")
with st.expander("Cấu hình API key"):
    st.code('KASHROCK_API_KEY = "API_KEY_CUA_BAN"', language="toml")
    st.caption("Streamlit Cloud → App → Settings → Secrets. Không đưa API key lên GitHub hoặc chat.")
