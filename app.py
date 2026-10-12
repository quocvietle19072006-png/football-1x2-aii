import os
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Esports Prediction Lab", page_icon="🎮", layout="wide")
st.title("🎮 Esports Prediction Lab")
st.caption("Ứng dụng riêng cho esports: CS2, LoL, Dota 2, Valorant và các giải mà nguồn dữ liệu cung cấp.")
st.warning("Bảng odds không phải dự đoán độc lập đã kiểm chứng. Ứng dụng không tự bịa trận đấu hoặc xác suất khi thiếu dữ liệu.")

BASE = "https://api.the-odds-api.com/v4"
def secret(name):
    try:
        v = st.secrets.get(name, "")
        if v: return str(v).strip()
    except Exception: pass
    return os.getenv(name, "").strip()

KEY = secret("THE_ODDS_API_KEY")
def get(path, params=None):
    if not KEY: raise RuntimeError("Thiếu THE_ODDS_API_KEY trong Streamlit Secrets.")
    p = dict(params or {})
    p["apiKey"] = KEY
    r = requests.get(BASE + path, params=p, timeout=25)
    if r.status_code == 401: raise RuntimeError("API key bị từ chối (401). Kiểm tra key tại nhà cung cấp.")
    if r.status_code == 403: raise RuntimeError("Gói API không có quyền truy cập dữ liệu/market này (403).")
    if r.status_code == 429: raise RuntimeError("Đã hết hạn mức API (429).")
    if not r.ok: raise RuntimeError(f"API lỗi HTTP {r.status_code}: {r.text[:200]}")
    return r.json()

with st.sidebar:
    st.header("Cài đặt")
    region = st.selectbox("Khu vực nhà cái", ["us", "uk", "eu", "au", "us,uk,eu"])
    fmt_label = st.selectbox("Định dạng odds", ["Decimal", "American"])
    fmt = "decimal" if fmt_label == "Decimal" else "american"
    markets = st.multiselect("Thị trường", ["h2h", "spreads", "totals"],
        default=["h2h"], format_func=lambda x: {"h2h":"Đội thắng / Moneyline","spreads":"Handicap","totals":"Tổng điểm/map"}[x])
    threshold = st.slider("Ngưỡng lọc chênh lệch giá (điểm %)", 0, 15, 3)

if not KEY:
    st.error("Chưa cấu hình THE_ODDS_API_KEY. Mở Manage app → Settings → Secrets.")
    st.stop()

@st.cache_data(ttl=900, show_spinner=False)
def sports(_marker):
    return get("/sports/")

@st.cache_data(ttl=90, show_spinner=False)
def odds(sport_key, region, markets, fmt, _marker):
    return get(f"/sports/{sport_key}/odds/", {"regions":region,"markets":markets,"oddsFormat":fmt,"dateFormat":"iso"})

try:
    catalog = sports(KEY[-4:])
except Exception as e:
    st.error(str(e)); st.stop()

# Only display entries whose names indicate esports; don't mislabel traditional sports.
terms = ["esport","e-sport","counter-strike","cs2","league of legends","dota","valorant","rainbow six","call of duty","rocket league","starcraft","overwatch"]
esports = []
for x in catalog or []:
    label = f'{x.get("key","")} {x.get("title","")} {x.get("group","")}'.lower()
    if any(t in label for t in terms): esports.append(x)

st.subheader("1. Chọn tựa game / giải")
if not esports:
    st.warning("API key chưa trả về giải nào có tên nhận diện là esports. Có thể nhà cung cấp hoặc gói hiện tại không hỗ trợ esports.")
    st.write("Danh mục API hiện trả về (để kiểm tra quyền dữ liệu):")
    st.dataframe(pd.DataFrame([{"Tên":x.get("title"),"Nhóm":x.get("group"),"Mã":x.get("key"),"Đang hoạt động":x.get("active")} for x in catalog or []]), use_container_width=True, hide_index=True)
    st.stop()

esports = sorted(esports, key=lambda x:(str(x.get("group","")),str(x.get("title",""))))
labels = [f'{x.get("title",x.get("key"))} ({x.get("key")})' for x in esports]
chosen = st.selectbox("Giải đấu", labels)
sport = esports[labels.index(chosen)]
st.caption(f'Mã giải: {sport.get("key")}')

st.subheader("2. Tải trận đấu và odds")
st.info("Bản đầu này phân tích xác suất ngầm định từ thị trường. Dự đoán độc lập cho từng game cần dữ liệu lịch sử riêng và phải backtest.")
if not markets:
    st.info("Chọn ít nhất một thị trường ở thanh Cài đặt.")
    st.stop()
if st.button("🔄 Tải odds và phân tích", type="primary", use_container_width=True):
    st.session_state["esports_run"] = True

def decimal(price):
    try:
        p = float(price)
        if fmt == "decimal": return p if p > 1 else None
        if p > 0: return 1 + p/100
        if p < 0: return 1 + 100/abs(p)
    except Exception: pass
    return None

def rows_from_events(events):
    rows = []
    for ev in events:
        # Market groups are normalized per bookmaker, market and line.
        grouped = {}
        for book in ev.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") not in markets: continue
                outs = []
                for o in market.get("outcomes", []):
                    d = decimal(o.get("price"))
                    if d:
                        outs.append({"selection":o.get("name",""),"description":o.get("description",""),
                                     "point":o.get("point"),"book":book.get("title",book.get("key","")),
                                     "odds":d,"implied":1/d,"market":market.get("key","")})
                total = sum(o["implied"] for o in outs)
                for o in outs:
                    o["fair"] = o["implied"]/total if total else None
                    k=(o["market"],o["selection"],o["description"],o["point"])
                    grouped.setdefault(k,[]).append(o)
        for (m,sel,desc,point), items in grouped.items():
            fairvals=[x["fair"] for x in items if x["fair"] is not None]
            if not fairvals: continue
            fair=sum(fairvals)/len(fairvals)
            best=max(items,key=lambda x:x["odds"])
            rows.append({"Bắt đầu (UTC)":ev.get("commence_time",""),
                         "Trận đấu":f'{ev.get("home_team","")} vs {ev.get("away_team","")}'.strip(" vs"),
                         "Thị trường":m,"Lựa chọn":sel,"Đội/người chơi":desc,"Mốc kèo":point,
                         "Odds tốt nhất":best["odds"],"Nhà cái tốt nhất":best["book"],
                         "Xác suất thị trường (%)":round(fair*100,2),
                         "Chênh lệch giá (điểm %)":round((fair-1/best["odds"])*100,2)})
    return rows

if st.session_state.get("esports_run"):
    try:
        with st.spinner("Đang tải dữ liệu esports..."):
            events=odds(sport["key"],region,",".join(markets),fmt,KEY[-4:])
        if not events:
            st.warning("Không có trận/odds cho giải này ở thời điểm hiện tại hoặc gói API không hỗ trợ thị trường đã chọn.")
            st.stop()
        rows=rows_from_events(events)
        if not rows:
            st.warning("API có sự kiện nhưng không có odds phù hợp.")
            st.stop()
        df=pd.DataFrame(rows)
        df["Bắt đầu (UTC)"]=pd.to_datetime(df["Bắt đầu (UTC)"],errors="coerce",utc=True).dt.strftime("%d/%m/%Y %H:%M")
        query=st.text_input("Tìm đội / tuyển thủ")
        if query.strip(): df=df[df["Trận đấu"].str.contains(query.strip(),case=False,na=False)]
        st.metric("Số trận có dữ liệu",df["Trận đấu"].nunique())
        st.dataframe(df,use_container_width=True,hide_index=True)
        st.subheader(f"Lọc chênh lệch giá ≥ {threshold} điểm %")
        shortlist=df[df["Chênh lệch giá (điểm %)"]>=threshold].sort_values("Chênh lệch giá (điểm %)",ascending=False)
        if shortlist.empty: st.info("Không có lựa chọn đạt ngưỡng. Không ép ra kèo khi dữ liệu chưa ủng hộ.")
        else: st.dataframe(shortlist,use_container_width=True,hide_index=True)
        st.download_button("⬇️ Tải CSV",df.to_csv(index=False).encode("utf-8-sig"),"esports_analysis.csv","text/csv")
    except Exception as e:
        st.error(str(e))

with st.expander("Lộ trình mô hình dự đoán độc lập"):
    st.markdown("Để dự đoán thực sự cho CS2/LoL/Dota 2/Valorant cần lịch sử trận, đội hình, map/patch, tỷ lệ thắng map/round, giải đấu và kết quả trước trận. Sau đó mới huấn luyện Elo hoặc mô hình ML, kiểm định theo thời gian và hiệu chỉnh xác suất. Không nên dùng odds nhà cái làm bằng chứng rằng mô hình đã dự đoán độc lập.")
