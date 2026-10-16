import os
import math
import requests
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Esports Match Predictor", page_icon="🎮", layout="wide")
st.title("🎮 Esports Match Predictor")
st.caption("Lịch thi đấu sắp tới và xác suất thắng tham khảo cho VALORANT, CS2 và League of Legends.")

KASHROCK_BASE = "https://kashrock.up.railway.app/v6/esports"
CITO_BASE = "https://api.citoapi.com/api/v1"
PANDASCORE_BASE = "https://api.pandascore.co"

# These are fallback ratings only, not live rankings. Unknown teams start at 1500.
DEFAULT_RATINGS = {
    "Gen.G": 1740, "T1": 1725, "Hanwha Life Esports": 1685,
    "KT Rolster": 1640, "Dplus KIA": 1600, "Bilibili Gaming": 1710,
    "Top Esports": 1665, "Anyone's Legend": 1615, "JD Gaming": 1590,
    "Weibo Gaming": 1575, "G2 Esports": 1600, "Fnatic": 1535,
    "Movistar KOI": 1510, "FlyQuest": 1550, "Team Liquid": 1540,
    "Cloud9": 1500, "GAM Esports": 1480, "PSG Talon": 1490,
    "Sentinels": 1650, "Fnatic VALORANT": 1600, "Paper Rex": 1660,
    "EDward Gaming": 1640, "Team Heretics": 1600, "LOUD VALORANT": 1570,
    "NAVI": 1600, "Vitality": 1660, "MOUZ": 1640, "FaZe Clan": 1620,
    "Natus Vincere": 1600, "The MongolZ": 1610, "Team Spirit": 1670,
    "G2 Esports CS2": 1640, "Aurora": 1620,
}

GAMES = {
    "League of Legends": {"kash_slug": "lol", "panda_slug": "lol", "cito_path": "/lol/schedule/upcoming"},
    "VALORANT": {"kash_slug": "valorant", "panda_slug": "valorant", "cito_path": None},
    "Counter-Strike 2": {"kash_slug": "cs2", "panda_slug": "csgo", "cito_path": None},
}


def secret(name):
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return os.getenv(name, "").strip()


def elo_prob(r_a, r_b):
    return 1 / (1 + 10 ** ((r_b - r_a) / 400))


def series_prob(p, best_of):
    needed = best_of // 2 + 1
    return sum(math.comb(best_of, k) * p**k * (1-p)**(best_of-k)
               for k in range(needed, best_of + 1))


def get_json(url, headers=None, params=None):
    r = requests.get(url, headers=headers or {}, params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()


def normalize_pandascore(items):
    rows = []
    for m in items if isinstance(items, list) else []:
        opponents = m.get("opponents") or []
        names = []
        for op in opponents:
            team = op.get("opponent") or {}
            names.append(team.get("name") or "TBD")
        if len(names) < 2:
            names = (names + ["TBD", "TBD"])[:2]
        league = m.get("league") or {}
        serie = m.get("serie") or {}
        rows.append({
            "Trận": f"{names[0]} vs {names[1]}",
            "Đội A": names[0], "Đội B": names[1],
            "Giải": league.get("name") or serie.get("full_name") or "Chưa rõ",
            "Bắt đầu (UTC)": m.get("begin_at") or "Chưa công bố",
            "Trạng thái": m.get("status") or "Chưa rõ",
            "Thể thức": m.get("match_type") or "Chưa rõ",
            "Nguồn": "PandaScore",
        })
    return rows


def normalize_kashrock(data):
    """Convert KashRock matches response into the app's common table format."""
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = data.get("matches") or data.get("data") or data.get("results") or []
        # Some responses return one match as the top-level object.
        if not candidates and (data.get("team1") or data.get("team2") or data.get("kr_match_id")):
            candidates = [data]
    else:
        candidates = []

    rows = []
    for m in candidates:
        if not isinstance(m, dict):
            continue
        a = m.get("team1") or m.get("team_a") or m.get("home_team") or "TBD"
        b = m.get("team2") or m.get("team_b") or m.get("away_team") or "TBD"
        if isinstance(a, dict):
            a = a.get("name") or "TBD"
        if isinstance(b, dict):
            b = b.get("name") or "TBD"
        rows.append({
            "Trận": f"{a} vs {b}",
            "Đội A": a, "Đội B": b,
            "Giải": m.get("tournament") or m.get("league") or m.get("event_name") or "Chưa rõ",
            "Bắt đầu (UTC)": m.get("event_time") or m.get("start_time") or m.get("begin_at") or "Chưa công bố",
            "Trạng thái": m.get("status") or "upcoming",
            "Thể thức": m.get("format") or m.get("match_type") or "Chưa rõ",
            "Nguồn": "KashRock",
        })
    return rows


def load_matches(game):
    kash_key = secret("KASHROCK_API_KEY")
    cito_key = secret("CITO_API_KEY")
    panda_key = secret("PANDASCORE_TOKEN")
    errors = []

    # KashRock is the primary source.
    if kash_key:
        try:
            slug = GAMES[game]["kash_slug"]
            data = get_json(
                f"{KASHROCK_BASE}/{slug}/matches",
                headers={"X-API-Key": kash_key, "Accept": "application/json"},
                params={"status": "upcoming", "limit": 100},
            )
            rows = normalize_kashrock(data)
            if rows:
                return rows, None, data
            hint = data.get("hint") if isinstance(data, dict) else None
            reason = data.get("reason") if isinstance(data, dict) else None
            return [], f"KashRock chưa trả về trận sắp tới. {reason or ''} {hint or ''}".strip(), data
        except Exception as e:
            errors.append(f"KashRock: {e}")

    # Optional legacy fallback: Cito for LoL.
    if game == "League of Legends" and cito_key:
        try:
            data = get_json(
                CITO_BASE + "/lol/schedule/upcoming",
                headers={"x-api-key": cito_key, "Accept": "application/json"},
                params={"leagueSlug": "worlds"},
            )
            candidates = data.get("matches") or data.get("data") or data.get("results") or [] if isinstance(data, dict) else (data if isinstance(data, list) else [])
            rows = []
            for m in candidates:
                teams = m.get("teams") or m.get("opponents") or []
                names = [t.get("name") or (t.get("team") or {}).get("name") or "TBD" for t in teams if isinstance(t, dict)]
                a = m.get("homeTeam") or m.get("home_team") or (names[0] if names else "TBD")
                b = m.get("awayTeam") or m.get("away_team") or (names[1] if len(names) > 1 else "TBD")
                if isinstance(a, dict): a = a.get("name", "TBD")
                if isinstance(b, dict): b = b.get("name", "TBD")
                rows.append({"Trận": f"{a} vs {b}", "Đội A": a, "Đội B": b,
                    "Giải": m.get("leagueName") or m.get("league_name") or "LoL Esports",
                    "Bắt đầu (UTC)": m.get("startTime") or m.get("begin_at") or m.get("start_time") or "Chưa rõ",
                    "Trạng thái": m.get("status") or "upcoming", "Thể thức": m.get("matchType") or m.get("match_type") or "Chưa rõ", "Nguồn": "Cito API"})
            if rows:
                return rows, None, data
            errors.append("Cito API không trả về trận theo cấu trúc dự kiến")
        except Exception as e:
            errors.append(f"Cito API: {e}")

    if panda_key:
        try:
            slug = GAMES[game]["panda_slug"]
            data = get_json(f"{PANDASCORE_BASE}/{slug}/matches/upcoming", headers={"Authorization": f"Bearer {panda_key}"}, params={"per_page": 100})
            return normalize_pandascore(data), None, data
        except Exception as e:
            errors.append(f"PandaScore: {e}")

    if not kash_key and not cito_key and not panda_key:
        return [], "Chưa cấu hình API key. Thêm KASHROCK_API_KEY trong Streamlit Secrets.", None
    return [], "Không tải được lịch. " + " | ".join(errors), None


tab_schedule, tab_predict, tab_setup = st.tabs(["📅 Trận sắp tới", "🔮 Dự đoán trận", "⚙️ Cấu hình API"])

with tab_schedule:
    game = st.selectbox("Chọn game", list(GAMES.keys()), key="schedule_game")
    if st.button("🔄 Tải/cập nhật lịch", type="primary"):
        st.session_state["match_cache"] = {}
        rows, error, raw = load_matches(game)
        st.session_state["match_cache"][game] = {"rows": rows, "error": error, "raw": raw}
    cached = st.session_state.get("match_cache", {}).get(game)
    if cached:
        if cached["rows"]:
            st.success(f"Đã tải {len(cached['rows'])} trận từ {cached['rows'][0]['Nguồn']}.")
            st.dataframe([{k: v for k, v in r.items() if k not in ("Đội A", "Đội B")} for r in cached["rows"]], use_container_width=True, hide_index=True)
            st.session_state["loaded_matches"] = cached["rows"]
        if cached["error"]:
            st.warning(cached["error"])
            if cached["raw"] is not None:
                with st.expander("Xem phản hồi API gốc"):
                    st.json(cached["raw"])
    else:
        st.info("Chọn game rồi nhấn **Tải/cập nhật lịch** để lấy lịch mới nhất qua API.")

def sync_selected_match():
    """Copy selected match names into text inputs when the selected match changes."""
    loaded_now = st.session_state.get("loaded_matches", [])
    selected_now = st.session_state.get("selected_match_predict")
    for item in loaded_now:
        if item.get("Trận") == selected_now:
            st.session_state["predict_a"] = item.get("Đội A", "TBD")
            st.session_state["predict_b"] = item.get("Đội B", "TBD")
            break

with tab_predict:
    st.subheader("🔮 Dự đoán trận và gợi ý thị trường")
    loaded = st.session_state.get("loaded_matches", [])
    if loaded:
        options = [r["Trận"] for r in loaded]
        if "selected_match_predict" not in st.session_state or st.session_state["selected_match_predict"] not in options:
            st.session_state["selected_match_predict"] = options[0]
            first_match = next(r for r in loaded if r["Trận"] == options[0])
            st.session_state["predict_a"] = first_match.get("Đội A", "TBD")
            st.session_state["predict_b"] = first_match.get("Đội B", "TBD")
        selected = st.selectbox("Chọn trận từ lịch đã tải", options, key="selected_match_predict", on_change=sync_selected_match)
        match = next(r for r in loaded if r["Trận"] == selected)
        st.caption(f"Giải: {match['Giải']} · Bắt đầu UTC: {match['Bắt đầu (UTC)']} · Nguồn: {match['Nguồn']}")
    else:
        st.info("Tải lịch ở tab **Trận sắp tới** trước, hoặc nhập hai đội thủ công.")
        st.session_state.setdefault("predict_a", "")
        st.session_state.setdefault("predict_b", "")

    team_a = st.text_input("Đội A", key="predict_a", placeholder="Tên đội A")
    team_b = st.text_input("Đội B", key="predict_b", placeholder="Tên đội B")
    col_a, col_b = st.columns(2)
    with col_a:
        elo_a = st.slider("Sức mạnh A (Elo tham khảo)", 1000, 2000, int(DEFAULT_RATINGS.get(team_a, 1500)), 5, key="elo_a")
    with col_b:
        elo_b = st.slider("Sức mạnh B (Elo tham khảo)", 1000, 2000, int(DEFAULT_RATINGS.get(team_b, 1500)), 5, key="elo_b")
    bo = st.selectbox("Thể thức series", [1, 3, 5], index=1, format_func=lambda x: f"BO{x}")
    st.markdown("#### Giá cược hiện tại (nếu có) — nhập để kiểm tra value")
    odds_col_a, odds_col_b = st.columns(2)
    with odds_col_a:
        odds_a = st.number_input(f"Odds thắng {team_a or 'đội A'}", min_value=1.01, max_value=100.0, value=1.90, step=0.05)
    with odds_col_b:
        odds_b = st.number_input(f"Odds thắng {team_b or 'đội B'}", min_value=1.01, max_value=100.0, value=1.90, step=0.05)

    if st.button("🔮 Phân tích và gợi ý kèo", type="primary"):
        if not team_a.strip() or not team_b.strip() or team_a.strip().lower() == team_b.strip().lower():
            st.error("Nhập tên hai đội khác nhau trước khi dự đoán.")
        else:
            p_map_a = elo_prob(elo_a, elo_b)
            p_series_a = series_prob(p_map_a, bo)
            p_series_b = 1 - p_series_a
            st.markdown("### Xác suất thắng series")
            c1, c2 = st.columns(2)
            c1.metric(f"{team_a} thắng", f"{p_series_a*100:.1f}%")
            c2.metric(f"{team_b} thắng", f"{p_series_b*100:.1f}%")
            st.progress(max(0, min(100, round(p_series_a*100))))

            # Expected value per unit stake, using user-entered decimal odds.
            ev_a = p_series_a * odds_a - 1
            ev_b = p_series_b * odds_b - 1
            st.markdown("### Gợi ý kèo")
            if bo == 1:
                st.write(f"**Kèo thắng trận:** {team_a if p_series_a >= p_series_b else team_b} có xác suất cao hơn theo Elo.")
            else:
                st.write(f"**Kèo thắng series:** {team_a if p_series_a >= p_series_b else team_b} là lựa chọn có xác suất mô hình cao hơn.")
                st.write(f"**Kèo tổng số map:** mô hình chỉ ước tính từ xác suất thắng từng map; không có dữ liệu lịch sử map nên chưa đủ cơ sở để khuyến nghị Over/Under đáng tin cậy.")
                st.write(f"**Kèo tỷ số series:** {team_a} thắng {bo//2+1}-0 hoặc {team_b} thắng {bo//2+1}-0 có thể được tính riêng, nhưng hiện chưa có dữ liệu map đủ tốt để xếp hạng chính xác các tỷ số.")
            st.markdown("#### Kiểm tra value theo odds bạn nhập")
            v1, v2 = st.columns(2)
            v1.metric(f"EV {team_a}", f"{ev_a*100:+.1f}%")
            v2.metric(f"EV {team_b}", f"{ev_b*100:+.1f}%")
            if max(ev_a, ev_b) > 0:
                value_team = team_a if ev_a >= ev_b else team_b
                value_ev = max(ev_a, ev_b)
                if value_ev > 0:
                    st.success(f"Theo các odds bạn nhập, {value_team} có EV dương ước tính ({value_ev*100:+.1f}%). Đây là tín hiệu cần kiểm tra thêm, không bảo đảm có lời.")
            else:
                st.warning("Chưa có kèo value theo mô hình ở mức odds đã nhập (EV không dương). Cân nhắc bỏ qua trận này.")
            st.warning("Giới hạn hiện tại: xác suất dựa trên Elo tham khảo, chưa học từ phong độ gần đây, đội hình, bản đồ, patch hay odds thị trường. Không xem đây là dự đoán chắc thắng; chỉ dùng để tham khảo.")

with tab_setup:
    st.subheader("Thêm API key an toàn")
    st.write("Trong Streamlit Cloud: mở app → Settings → Secrets. Không đăng key lên GitHub và không gửi key trong chat.")
    st.code('KASHROCK_API_KEY = "dan_key_cua_ban"', language="toml")
    st.markdown("- **KashRock**: lịch trận sắp tới cho LoL, VALORANT và CS2. Tài liệu: https://www.kashrock.com/docs/endpoints/matches")
    st.caption("KashRock là nguồn ưu tiên. Cito/PandaScore chỉ được dùng làm phương án dự phòng nếu bạn đã cấu hình các key đó.")

st.divider()
st.caption("Lịch được lấy trực tiếp khi bạn nhấn tải. Gợi ý kèo và EV chỉ là ước tính theo Elo cùng odds do bạn nhập; chưa phải mô hình đã được kiểm định và không bảo đảm lợi nhuận.")
