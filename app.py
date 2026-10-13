
import os
import math
import random
import requests
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Worlds 2026 Predictor",
    page_icon="🏆",
    layout="wide",
)

st.title("🏆 Worlds 2026 Predictor")
st.caption("League of Legends • Dự đoán CKTG • Tối ưu cho điện thoại")

st.info(
    "Dự đoán mang tính tham khảo. Khi chưa có dữ liệu thi đấu xác thực, "
    "hãy nhập sức mạnh đội theo đánh giá của bạn; app không tự tạo kết quả thật."
)

# ---------- DATA ----------
DEFAULT_TEAMS = [
    {"Đội": "T1", "Khu vực": "LCK", "Sức mạnh": 85},
    {"Đội": "Gen.G", "Khu vực": "LCK", "Sức mạnh": 88},
    {"Đội": "Hanwha Life Esports", "Khu vực": "LCK", "Sức mạnh": 82},
    {"Đội": "KT Rolster", "Khu vực": "LCK", "Sức mạnh": 78},
    {"Đội": "Bilibili Gaming", "Khu vực": "LPL", "Sức mạnh": 84},
    {"Đội": "Top Esports", "Khu vực": "LPL", "Sức mạnh": 81},
    {"Đội": "Anyone's Legend", "Khu vực": "LPL", "Sức mạnh": 79},
    {"Đội": "Weibo Gaming", "Khu vực": "LPL", "Sức mạnh": 77},
    {"Đội": "G2 Esports", "Khu vực": "LEC", "Sức mạnh": 79},
    {"Đội": "Movistar KOI", "Khu vực": "LEC", "Sức mạnh": 73},
    {"Đội": "Fnatic", "Khu vực": "LEC", "Sức mạnh": 72},
    {"Đội": "Team Heretics", "Khu vực": "LEC", "Sức mạnh": 69},
    {"Đội": "FlyQuest", "Khu vực": "LTA", "Sức mạnh": 76},
    {"Đội": "Cloud9", "Khu vực": "LTA", "Sức mạnh": 72},
    {"Đội": "100 Thieves", "Khu vực": "LTA", "Sức mạnh": 68},
    {"Đội": "PSG Talon", "Khu vực": "LCP", "Sức mạnh": 73},
    {"Đội": "CTBC Flying Oyster", "Khu vực": "LCP", "Sức mạnh": 74},
    {"Đội": "GAM Esports", "Khu vực": "LCP", "Sức mạnh": 69},
    {"Đội": "Vikings Esports", "Khu vực": "LCP", "Sức mạnh": 67},
]

if "teams" not in st.session_state:
    st.session_state.teams = pd.DataFrame(DEFAULT_TEAMS)

def probability(a, b):
    # Elo-style estimate; this is a simple heuristic, not a trained model.
    return 1 / (1 + 10 ** ((b - a) / 16))

def simulate_series(a, b, best_of, rng):
    wins_needed = best_of // 2 + 1
    wa, wb = 0, 0
    p = probability(a, b)
    while wa < wins_needed and wb < wins_needed:
        if rng.random() < p:
            wa += 1
        else:
            wb += 1
    return wa, wb

def get_schedule():
    """Optional integration: requires a compatible endpoint and API key."""
    try:
        api_key = st.secrets.get("LOL_ESPORTS_API_KEY", "")
    except Exception:
        api_key = os.getenv("LOL_ESPORTS_API_KEY", "")

    endpoint = os.getenv("LOL_ESPORTS_SCHEDULE_URL", "")
    if not api_key or not endpoint:
        return None, "Chưa cấu hình nguồn lịch tự động."

    try:
        response = requests.get(
            endpoint,
            headers={"x-api-key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        return response.json(), None
    except Exception as exc:
        return None, f"Không lấy được lịch tự động: {exc}"

tab1, tab2, tab3, tab4 = st.tabs([
    "⚔️ Dự đoán trận",
    "🏆 Ứng viên vô địch",
    "📋 Danh sách đội",
    "📅 Lịch thi đấu",
])

teams = st.session_state.teams.copy()
teams["Sức mạnh"] = pd.to_numeric(
    teams["Sức mạnh"], errors="coerce"
).fillna(50).clip(1, 100)

with tab1:
    st.subheader("Dự đoán hai đội")
    names = teams["Đội"].astype(str).tolist()

    if len(names) < 2:
        st.warning("Cần nhập ít nhất hai đội.")
    else:
        c1, c2 = st.columns(2)
        team_a = c1.selectbox("Đội A", names, index=0)
        team_b = c2.selectbox(
            "Đội B", names, index=1 if len(names) > 1 else 0
        )
        series = st.radio(
            "Thể thức",
            ["BO1", "BO3", "BO5"],
            horizontal=True,
            index=1,
        )

        if team_a == team_b:
            st.warning("Hãy chọn hai đội khác nhau.")
        else:
            a = float(teams.loc[teams["Đội"] == team_a, "Sức mạnh"].iloc[0])
            b = float(teams.loc[teams["Đội"] == team_b, "Sức mạnh"].iloc[0])
            p = probability(a, b)

            st.markdown("### Tỷ lệ thắng ước tính")
            m1, m2 = st.columns(2)
            m1.metric(team_a, f"{p * 100:.1f}%")
            m2.metric(team_b, f"{(1-p) * 100:.1f}%")

            st.progress(int(round(p * 100)))
            st.write(
                f"Chênh lệch sức mạnh: **{a-b:+.0f} điểm** "
                f"(theo bảng sức mạnh đang nhập)."
            )

            best_of = int(series[-1])
            rng = random.Random(2026)
            sims = 5000
            wins_a = 0
            for _ in range(sims):
                wa, wb = simulate_series(a, b, best_of, rng)
                if wa > wb:
                    wins_a += 1

            st.write(
                f"Trong mô phỏng {sims:,} loạt {series}, "
                f"{team_a} thắng khoảng **{wins_a/sims*100:.1f}%**."
            )
            st.caption(
                "Đây là mô hình Elo đơn giản dựa trên điểm sức mạnh tự nhập, "
                "không phải dự báo đã được huấn luyện bằng dữ liệu trận thực."
            )

with tab2:
    st.subheader("Xếp hạng ứng viên vô địch")
    ranked = teams.sort_values("Sức mạnh", ascending=False).copy()
    ranked.insert(0, "Hạng mô hình", range(1, len(ranked) + 1))
    ranked["Điểm sức mạnh"] = ranked["Sức mạnh"].round(1)
    st.dataframe(
        ranked[["Hạng mô hình", "Đội", "Khu vực", "Điểm sức mạnh"]],
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Thứ hạng chỉ dựa trên điểm sức mạnh trong bảng, không khẳng định "
        "đây là danh sách hạt giống hoặc đội đã đủ điều kiện tham dự."
    )

    if len(ranked) >= 2:
        st.subheader("Mô phỏng giải đấu loại trực tiếp")
        n = st.selectbox("Số đội mô phỏng", [4, 8, 16], index=1)
        eligible = ranked.head(min(n, len(ranked)))["Đội"].tolist()

        if len(eligible) < n:
            st.warning(f"Hiện chỉ có {len(eligible)} đội trong bảng.")
        elif st.button("Chạy mô phỏng nhánh đấu"):
            power = dict(zip(teams["Đội"], teams["Sức mạnh"]))
            rng = random.Random()
            round_teams = eligible[:]
            round_num = 1

            while len(round_teams) > 1:
                st.markdown(f"**Vòng {round_num}**")
                next_round = []
                for i in range(0, len(round_teams), 2):
                    left, right = round_teams[i], round_teams[i + 1]
                    wl, wr = simulate_series(
                        float(power[left]), float(power[right]), 5, rng
                    )
                    winner = left if wl > wr else right
                    st.write(
                        f"{left} {wl}–{wr} {right} → "
                        f"**Đi tiếp: {winner}**"
                    )
                    next_round.append(winner)
                round_teams = next_round
                round_num += 1

            st.success(f"Đội vô địch trong lần mô phỏng: {round_teams[0]}")

with tab3:
    st.subheader("Chỉnh sửa dữ liệu đội")
    st.caption(
        "Danh sách ban đầu là ví dụ để chạy thử, không phải danh sách "
        "đội Worlds 2026 đã xác nhận. Hãy cập nhật theo thông tin chính thức."
    )
    edited = st.data_editor(
        st.session_state.teams,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sức mạnh": st.column_config.NumberColumn(
                min_value=1, max_value=100, step=1
            )
        },
        key="team_editor",
    )

    if st.button("Lưu bảng đội"):
        if "Đội" in edited.columns:
            edited = edited.dropna(subset=["Đội"])
            edited["Đội"] = edited["Đội"].astype(str).str.strip()
            edited = edited[edited["Đội"] != ""]
            edited = edited.drop_duplicates(subset=["Đội"], keep="last")
            st.session_state.teams = edited.reset_index(drop=True)
            st.success("Đã cập nhật bảng đội.")
            st.rerun()

    uploaded = st.file_uploader("Hoặc tải CSV danh sách đội", type=["csv"])
    if uploaded is not None:
        try:
            imported = pd.read_csv(uploaded)
            required = {"Đội", "Khu vực", "Sức mạnh"}
            if required.issubset(imported.columns):
                st.session_state.teams = imported
                st.success("Đã nhập CSV. Nhấn tải lại trang nếu cần.")
            else:
                st.error("CSV cần các cột: Đội, Khu vực, Sức mạnh.")
        except Exception as exc:
            st.error(f"Không đọc được CSV: {exc}")

with tab4:
    st.subheader("Lịch thi đấu")
    st.write(
        "Lịch chính thức cần được lấy từ một API có quyền truy cập và "
        "cấu trúc dữ liệu phù hợp."
    )
    if st.button("Kiểm tra nguồn lịch tự động"):
        data, error = get_schedule()
        if error:
            st.warning(error)
            st.info(
                "Bạn vẫn có thể dùng các chức năng dự đoán và mô phỏng. "
                "Không có lịch giả được tự tạo."
            )
        else:
            st.success("Đã nhận phản hồi từ nguồn đã cấu hình.")
            st.json(data)

st.divider()
st.caption(
    "Worlds 2026 Predictor • Dự đoán chỉ mang tính tham khảo, "
    "không bảo đảm kết quả thi đấu."
)
