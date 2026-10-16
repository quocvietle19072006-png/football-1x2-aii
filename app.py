import requests
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Esports Match Analyst", page_icon="🎮", layout="wide")
st.title("🎮 Esports Match Analyst")
st.caption("Phân tích từ dữ liệu esports đã công bố. Không dùng Elo giả, không tự tạo odds.")

BASE = "https://kashrock.up.railway.app"
SPORTS = {
    "League of Legends": "lol",
    "VALORANT": "valorant",
    "Counter-Strike 2": "cs2",
}

@st.cache_data(ttl=300, show_spinner=False)
def get_json(url, headers=None, params=None):
    r = requests.get(url, headers=headers or {}, params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("pages", "matches", "data", "results", "events"):
            if isinstance(x.get(k), list):
                return x[k]
    return []

def label_page(p):
    return f"{p.get('kind', 'page').upper()} · {p.get('slug', 'unknown')}"

def render_facts(obj, depth=0):
    """Display returned facts without inventing missing fields."""
    if depth > 3:
        st.json(obj)
        return
    if isinstance(obj, dict):
        preferred = [
            "available", "reason", "sport", "match", "teams", "team1", "team2",
            "odds", "markets", "last_five", "form", "head_to_head", "h2h",
            "map_pool", "maps", "props", "targets", "summary", "analysis"
        ]
        shown = set()
        for k in preferred:
            if k in obj:
                shown.add(k)
                v = obj[k]
                st.markdown(f"**{k.replace('_', ' ').title()}**")
                if isinstance(v, (dict, list)):
                    render_facts(v, depth + 1)
                else:
                    st.write(v)
        remaining = {k: v for k, v in obj.items() if k not in shown}
        if remaining:
            with st.expander("Các trường dữ liệu khác từ nguồn"):
                st.json(remaining)
    elif isinstance(obj, list):
        if not obj:
            st.info("Nguồn không trả dữ liệu cho mục này.")
        elif all(isinstance(x, dict) for x in obj):
            st.dataframe(obj, use_container_width=True, hide_index=True)
        else:
            st.write(obj)
    else:
        st.write(obj)

game = st.selectbox("Chọn game", list(SPORTS.keys()))
slug = SPORTS[game]
tab1, tab2, tab3 = st.tabs(["📊 Phân tích từ dữ liệu thật", "📅 Trận đã công bố", "⚙️ Cấu hình"])

with tab1:
    st.write("Chọn một trận đã có breakdown công khai để xem phong độ gần đây, odds/market (nếu có), map pool và props.")
    if st.button("🔄 Tải dữ liệu mới", type="primary"):
        get_json.clear()
    try:
        index_data = get_json(f"{BASE}/v7/{slug}/breakdown/index")
        pages = as_list(index_data)
        match_pages = [p for p in pages if isinstance(p, dict) and p.get("kind") == "match" and p.get("slug")]
        if match_pages:
            labels = [label_page(p) for p in match_pages]
            selected_label = st.selectbox("Chọn trận", labels, key=f"match_{slug}")
            selected = match_pages[labels.index(selected_label)]
            url = f"{BASE}/v7/{slug}/breakdown/published/match/{selected['slug']}"
            with st.spinner("Đang tải breakdown từ nguồn..."):
                bundle = get_json(url)
            if isinstance(bundle, dict) and bundle.get("available") is False:
                st.warning(bundle.get("reason", "Nguồn chưa có breakdown cho trận này."))
                st.json(bundle)
            else:
                st.success("Đã tải dữ liệu từ KashRock public breakdown.")
                render_facts(bundle)
                st.warning("Chỉ chốt kèo khi nguồn có odds/line thực tế. Nếu odds hoặc phong độ không xuất hiện ở dữ liệu trên thì app không tự bịa hoặc suy diễn thành kèo value.")
        else:
            st.warning("Nguồn hiện không có trang breakdown trận nào được công bố cho game này.")
            st.json(index_data)
    except Exception as e:
        st.error(f"Không tải được dữ liệu nguồn: {e}")
        st.caption("Thử lại sau. API công khai có thể tạm gián đoạn.")

with tab2:
    try:
        index_data = get_json(f"{BASE}/v7/{slug}/breakdown/index")
        pages = as_list(index_data)
        if pages:
            st.dataframe(
                [{"Loại": p.get("kind"), "Slug": p.get("slug"), "Game": p.get("sport", slug)} for p in pages if isinstance(p, dict)],
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Không có trang nào được công bố cho game này.")
    except Exception as e:
        st.error(f"Không tải được danh sách: {e}")

with tab3:
    st.markdown("### Nguồn dữ liệu")
    st.write("App dùng các trang breakdown công khai của KashRock v7, không cần API key cho dữ liệu đã công bố.")
    st.code(f"{BASE}/v7/{slug}/breakdown/index")
    st.markdown("### Giới hạn trung thực")
    st.markdown("""
- Không có Elo hoặc rating giả.
- App chỉ hiển thị dữ liệu mà nguồn trả về.
- Không phải mọi trận đều có breakdown công khai.
- Endpoint tạo breakdown theo yêu cầu cần gói/API key phù hợp; app không giả vờ rằng nguồn miễn phí có dữ liệu đó.
- Xác suất thắng, handicap, Tài/Xỉu và value chỉ nên tính khi có dữ liệu trận/odds đủ dùng; nếu thiếu, app sẽ không tự tạo phần trăm.
""")

st.divider()
st.caption(f"Cập nhật khi tải · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · Dữ liệu công khai, có thể thiếu hoặc gián đoạn.")
