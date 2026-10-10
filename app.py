import math
import statistics
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import requests
import streamlit as st

st.set_page_config(page_title="Independent Multi-Sport Bet Analyzer", page_icon="🎯", layout="wide")
ODDS_BASE = "https://api.the-odds-api.com/v4"
FOOTBALL_BASE = "https://v3.football.api-sports.io"
ODDS_KEY = st.secrets.get("THE_ODDS_API_KEY", "")
FOOTBALL_KEY = st.secrets.get("API_FOOTBALL_KEY", st.secrets.get("APISPORTS_KEY", ""))

st.title("🎯 Independent Multi-Sport Bet Analyzer")
st.caption("Sàng lọc kèo trước trận • Xếp hạng lựa chọn • Tách rõ mô hình thống kê và tham chiếu thị trường")

if not ODDS_KEY:
    st.error("Thiếu THE_ODDS_API_KEY trong Streamlit Secrets.")
    st.code('THE_ODDS_API_KEY = "YOUR_KEY_HERE"', language="toml")
    st.stop()

session = requests.Session()
session.headers.update({"User-Agent": "IndependentMultiSportBetAnalyzer/3.0"})


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




# ---------------- Independent statistical models (v3) ----------------
# Football: Poisson goal model built from recent completed API-Football fixtures.
# Tennis: Elo model trained from a user-provided historical match CSV.
import csv
from io import StringIO

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def poisson_1x2(home_lambda, away_lambda, max_goals=10):
    ph = [poisson_pmf(i, home_lambda) for i in range(max_goals + 1)]
    pa = [poisson_pmf(i, away_lambda) for i in range(max_goals + 1)]
    home = draw = away = total = 0.0
    for h, hp in enumerate(ph):
        for a, ap in enumerate(pa):
            p = hp * ap
            total += p
            if h > a: home += p
            elif h == a: draw += p
            else: away += p
    if total:
        return {"home": home / total, "draw": draw / total, "away": away / total}
    return {"home": 1/3, "draw": 1/3, "away": 1/3}

@st.cache_data(ttl=1800, show_spinner=False)
def team_id_search(team_name):
    resp, err = get_football("/teams", {"search": team_name})
    if err or not resp:
        return None
    # Prefer a close name match, but reject weak matches.
    ranked = sorted(resp, key=lambda x: team_match_score(team_name, x.get("team", {}).get("name", "")), reverse=True)
    if not ranked or team_match_score(team_name, ranked[0].get("team", {}).get("name", "")) < 0.60:
        return None
    return ranked[0].get("team", {}).get("id")

@st.cache_data(ttl=1800, show_spinner=False)
def recent_team_fixtures(team_id, before_date, last=12):
    resp, err = get_football("/fixtures", {"team": team_id, "last": last, "status": "FT", "to": before_date})
    if err:
        return None
    return resp or []

def summarize_team_fixtures(fixtures, team_id):
    scored, conceded, home_scored, home_conceded, away_scored, away_conceded = [], [], [], [], [], []
    for f in fixtures or []:
        teams, goals = f.get("teams", {}), f.get("goals", {})
        h_id = teams.get("home", {}).get("id")
        a_id = teams.get("away", {}).get("id")
        hg, ag = number(goals.get("home")), number(goals.get("away"))
        if hg is None or ag is None:
            continue
        if h_id == team_id:
            scored.append(hg); conceded.append(ag); home_scored.append(hg); home_conceded.append(ag)
        elif a_id == team_id:
            scored.append(ag); conceded.append(hg); away_scored.append(ag); away_conceded.append(hg)
    if len(scored) < 4:
        return None
    avg = lambda xs, fallback: (sum(xs) / len(xs)) if xs else fallback
    return {
        "n": len(scored), "scored": avg(scored, 1.2), "conceded": avg(conceded, 1.2),
        "home_scored": avg(home_scored, avg(scored, 1.2)),
        "home_conceded": avg(home_conceded, avg(conceded, 1.2)),
        "away_scored": avg(away_scored, avg(scored, 1.2)),
        "away_conceded": avg(away_conceded, avg(conceded, 1.2)),
    }

def independent_football_model(home, away, kickoff_iso):
    if not FOOTBALL_KEY:
        return None, "Cần thêm API_FOOTBALL_KEY trong Streamlit Secrets để lấy kết quả lịch sử; chưa thể tính mô hình độc lập."
    kick = dt_parse(kickoff_iso)
    if not kick:
        return None, "Không xác định được ngày trận."
    h_id, a_id = team_id_search(home), team_id_search(away)
    if not h_id or not a_id:
        return None, "Không ghép được ID hai đội từ API-Football."
    cutoff = (kick.astimezone(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    hf, af = recent_team_fixtures(h_id, cutoff), recent_team_fixtures(a_id, cutoff)
    if hf is None or af is None:
        return None, "Không truy vấn được lịch sử; kiểm tra khóa API hoặc hạn mức."
    hs, ass = summarize_team_fixtures(hf, h_id), summarize_team_fixtures(af, a_id)
    if not hs or not ass:
        return None, "Chưa đủ ít nhất 4 trận đã kết thúc cho mỗi đội."
    # League-wide neutral baseline; shrunk towards 1.25 goals to reduce small-sample extremes.
    home_attack = 0.65 * hs["home_scored"] + 0.35 * hs["scored"]
    home_def_weakness = 0.65 * ass["away_conceded"] + 0.35 * ass["conceded"]
    away_attack = 0.65 * ass["away_scored"] + 0.35 * ass["scored"]
    away_def_weakness = 0.65 * hs["home_conceded"] + 0.35 * hs["conceded"]
    h_lam = max(0.15, min(3.8, 0.5 * home_attack + 0.5 * home_def_weakness))
    a_lam = max(0.15, min(3.8, 0.5 * away_attack + 0.5 * away_def_weakness))
    probs = poisson_1x2(h_lam, a_lam)
    return {
        "home_lambda": h_lam, "away_lambda": a_lam, "probs": probs,
        "sample_home": hs["n"], "sample_away": ass["n"],
        "expected_total": h_lam + a_lam,
    }, None


@st.cache_data(ttl=21600, show_spinner=False)
def tennis_historical_elo(player_a, player_b, tour="atp", years_back=5, surface="All"):
    """Fetch public Jeff Sackmann match-result CSVs and compute Elo; network/cache dependent."""
    import pandas as pd
    current_year = datetime.now(timezone.utc).year
    base = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master" if tour == "atp" else "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"
    ratings = {}
    used = 0
    files_found = 0
    # Read chronologically, using only completed match results from available yearly datasets.
    for year in range(current_year - years_back, current_year + 1):
        url = f"{base}/{tour}_matches_{year}.csv" if tour == "atp" else f"{base}/wta_matches_{year}.csv"
        try:
            response = session.get(url, timeout=15)
            if response.status_code != 200:
                continue
            df = pd.read_csv(StringIO(response.text))
            files_found += 1
        except Exception:
            continue
        required = {"winner_name", "loser_name"}
        if not required.issubset(set(df.columns)):
            continue
        for _, row in df.iterrows():
            surf = str(row.get("surface", "") or "")
            if surface != "All" and surf.lower() != surface.lower():
                continue
            winner, loser = str(row.get("winner_name", "") or "").strip(), str(row.get("loser_name", "") or "").strip()
            if not winner or not loser or winner == "nan" or loser == "nan":
                continue
            rw, rl = ratings.get(winner, 1500.0), ratings.get(loser, 1500.0)
            expected = 1.0 / (1.0 + 10.0 ** ((rl - rw) / 400.0))
            # Modest K factor: an Elo baseline, not a calibrated betting probability.
            k = 32.0
            ratings[winner] = rw + k * (1.0 - expected)
            ratings[loser] = rl + k * (0.0 - (1.0 - expected))
            used += 1
    if files_found == 0:
        return None, "Không truy cập được bộ dữ liệu lịch sử tennis công khai. Có thể mạng bị chặn hoặc nguồn dữ liệu tạm thời không khả dụng."
    def find_player(name):
        target = name.strip().lower()
        exact = [p for p in ratings if p.lower() == target]
        if exact:
            return exact[0]
        # Conservative fuzzy match, avoiding ambiguous short names.
        candidates = sorted(
            [(SequenceMatcher(None, target, p.lower()).ratio(), p) for p in ratings],
            reverse=True
        )
        if candidates and candidates[0][0] >= 0.78 and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] > 0.04):
            return candidates[0][1]
        return None
    pa, pb = find_player(player_a), find_player(player_b)
    if not pa or not pb:
        return None, "Không khớp chắc chắn tên một hoặc cả hai tay vợt trong dữ liệu lịch sử. Hãy nhập tên theo dữ liệu hoặc dùng CSV."
    ra, rb = ratings[pa], ratings[pb]
    p = 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))
    return {"p_a": p, "p_b": 1-p, "elo_a": ra, "elo_b": rb, "n": used,
            "player_a_matched": pa, "player_b_matched": pb, "files": files_found}, None

def tennis_elo_from_csv(uploaded, player_a, player_b, surface=None):
    """CSV columns: winner, loser; optional surface. Computes Elo from historic match order."""
    try:
        raw = uploaded.getvalue().decode("utf-8-sig")
        rows = list(csv.DictReader(StringIO(raw)))
    except Exception:
        return None, "Không đọc được CSV. Hãy lưu CSV dạng UTF-8."
    if not rows or not {"winner", "loser"}.issubset({x.strip().lower() for x in rows[0].keys()}):
        return None, "CSV cần có hai cột tên chính xác: winner, loser; có thể thêm cột surface."
    # Normalize field names.
    norm = [{str(k).strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]
    elo = {}
    used = 0
    for r in norm:
        if surface and r.get("surface") and r["surface"].lower() != surface.lower():
            continue
        w, l = r.get("winner", ""), r.get("loser", "")
        if not w or not l:
            continue
        ew, el = elo.get(w, 1500.0), elo.get(l, 1500.0)
        expected = 1 / (1 + 10 ** ((el - ew) / 400))
        k = 32
        elo[w] = ew + k * (1 - expected)
        elo[l] = el + k * (0 - (1 - expected))
        used += 1
    if used < 50:
        return None, f"Chỉ có {used} trận hợp lệ sau lọc; cần tối thiểu 50 trận lịch sử để hiển thị tham khảo."
    ra, rb = elo.get(player_a, 1500.0), elo.get(player_b, 1500.0)
    p = 1 / (1 + 10 ** ((rb - ra) / 400))
    return {"p_a": p, "p_b": 1-p, "elo_a": ra, "elo_b": rb, "n": used}, None


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

if is_soccer:
    st.subheader("⚽ Dự đoán độc lập: mô hình bàn thắng Poisson")
    with st.spinner("Đang tính từ các trận lịch sử đã kết thúc..."):
        independent, model_error = independent_football_model(
            event.get("home_team", ""), event.get("away_team", ""), event.get("commence_time", "")
        )
    if model_error:
        st.warning(model_error)
    else:
        p = independent["probs"]
        st.caption("Mô hình riêng của app dùng trung bình bàn thắng ghi/thủng lưới gần đây; chưa phải mô hình đã được backtest đầy đủ.")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{event.get('home_team', 'Chủ nhà')} thắng", f"{p['home']*100:.1f}%")
        c2.metric("Hòa", f"{p['draw']*100:.1f}%")
        c3.metric(f"{event.get('away_team', 'Đội khách')} thắng", f"{p['away']*100:.1f}%")
        st.write(f"Bàn thắng kỳ vọng: **{independent['home_lambda']:.2f} – {independent['away_lambda']:.2f}** (tổng {independent['expected_total']:.2f})")
        st.caption(f"Mẫu lịch sử: {independent['sample_home']} trận đội chủ nhà, {independent['sample_away']} trận đội khách. Chưa điều chỉnh đầy đủ theo sức mạnh giải, đội hình và chấn thương.")
        # Compute independent-model edge for exact 1X2 outcomes where a mapping is clear.
        for r in rows:
            if r["market_key"] in ("h2h", "h2h_3_way"):
                sel = r["selection"].lower()
                if event.get("home_team", "").lower() in sel:
                    mp = p["home"]
                elif event.get("away_team", "").lower() in sel:
                    mp = p["away"]
                elif "draw" in sel or "tie" in sel or "draw" == sel:
                    mp = p["draw"]
                else:
                    continue
                r["p_model"] = mp
                r["model_edge"] = mp * r["best_odds"] - 1
        st.markdown("**Kèo 1X2 theo mô hình độc lập**")
        mapped = [r for r in rows if "model_edge" in r]
        for r in sorted(mapped, key=lambda x: x["model_edge"], reverse=True):
            st.write(f"- **{r['selection']}** · xác suất mô hình {r['p_model']*100:.1f}% · odds {r['best_odds']:.2f} · chênh lệch ước tính {r['model_edge']*100:+.1f}%")
            if r["model_edge"] >= 0.03:
                st.success("Có thể nghiên cứu thêm; chưa phải khuyến nghị chắc thắng.")
            elif r["model_edge"] > 0:
                st.info("Lợi thế ước tính mỏng; sai số mô hình có thể xóa lợi thế.")
            else:
                st.caption("Mô hình chưa thấy lợi thế giá ở lựa chọn này.")

st.subheader("🎾 Mô hình Elo tennis từ dữ liệu lịch sử")
st.write("Thử lấy kết quả lịch sử công khai tự động trước; nếu nguồn không khả dụng hoặc không khớp tên, bạn vẫn có thể tải CSV.")
ta, tb = st.columns(2)
with ta:
    player_a = st.text_input("Tên tay vợt A", value=event.get("home_team", ""))
with tb:
    player_b = st.text_input("Tên tay vợt B", value=event.get("away_team", ""))
tc1, tc2, tc3 = st.columns(3)
with tc1:
    tennis_tour = st.selectbox("Tour", ["wta", "atp"], index=0 if any(x in (event.get("home_team","")+event.get("away_team","")).lower() for x in ["mirra", "nikola", "iga", "coco"]) else 1)
with tc2:
    tennis_years = st.selectbox("Dữ liệu lịch sử", [3, 5, 8], index=1)
with tc3:
    tennis_surface = st.selectbox("Mặt sân", ["All", "Hard", "Clay", "Grass", "Carpet"])
if st.button("Tính Elo tennis từ dữ liệu công khai", use_container_width=True):
    with st.spinner("Đang tải dữ liệu lịch sử và tính Elo..."):
        elo_result, elo_error = tennis_historical_elo(player_a.strip(), player_b.strip(), tennis_tour, tennis_years, tennis_surface)
    if elo_error:
        st.warning(elo_error)
    else:
        ec1, ec2 = st.columns(2)
        ec1.metric(f"{elo_result['player_a_matched']} thắng theo Elo", f"{elo_result['p_a']*100:.1f}%")
        ec2.metric(f"{elo_result['player_b_matched']} thắng theo Elo", f"{elo_result['p_b']*100:.1f}%")
        st.caption(f"Elo A: {elo_result['elo_a']:.0f}; Elo B: {elo_result['elo_b']:.0f}; {elo_result['n']:,} trận dùng trong dữ liệu; {elo_result['files']} tệp năm tải được.")
        st.warning("Đây là xác suất Elo cơ sở từ kết quả lịch sử, chưa được hiệu chuẩn/backtest theo giải đấu, mặt sân và chấn thương; không dùng đơn lẻ làm lệnh cược.")
st.write("**Tùy chọn dự phòng: tải CSV của riêng bạn** (cột `winner`, `loser`, có thể thêm `surface`).")
tennis_csv = st.file_uploader("CSV kết quả tennis lịch sử", type=["csv"])
if tennis_csv is not None and st.button("Tính Elo từ CSV", use_container_width=True):
    elo_result, elo_error = tennis_elo_from_csv(tennis_csv, player_a.strip(), player_b.strip(), None if tennis_surface == "All" else tennis_surface)
    if elo_error:
        st.warning(elo_error)
    else:
        st.metric(f"{player_a} thắng theo Elo CSV", f"{elo_result['p_a']*100:.1f}%")
        st.metric(f"{player_b} thắng theo Elo CSV", f"{elo_result['p_b']*100:.1f}%")
        st.caption(f"Elo A: {elo_result['elo_a']:.0f}; Elo B: {elo_result['elo_b']:.0f}; số trận dùng: {elo_result['n']}.")

st.subheader("📊 Tất cả lựa chọn")
display = []
for r in rows:
    display.append({
        "Thị trường": r["market"],
        "Lựa chọn": r["selection"],
        "Xác suất tham chiếu": f"{r['p_market']*100:.1f}%",
        "Xác suất mô hình độc lập": f"{r['p_model']*100:.1f}%" if "p_model" in r else "—",
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
