import streamlit as st
import pandas as pd
import math

st.set_page_config(page_title="1Mphamvu — Swap Booking", layout="wide")

# Brand header
st.markdown("### 1Mphamvu")
st.title("Swap Booking — Mvera → Salima")
st.caption("JIT booking with inbound arrivals, flips, and estimated rest")

SPEED = 60.0
NEXT_LEG_KM = 85.0
FULL_CHARGE_MIN = 95.0
SWAP_MIN = 5.0

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def bezier_curve(p0, p1, n=100, bend=0.0):
    (lat0, lon0), (lat1, lon1) = p0, p1
    mid_lat, mid_lon = (lat0 + lat1) / 2, (lon0 + lon1) / 2
    dlat, dlon = lat1 - lat0, lon1 - lon0
    perp_lat, perp_lon = -dlon, dlat
    norm = math.hypot(perp_lat, perp_lon) or 1.0
    ctrl_lat = mid_lat + bend * perp_lat / norm
    ctrl_lon = mid_lon + bend * perp_lon / norm
    pts = []
    for i in range(n + 1):
        t = i / n
        lat = (1-t)**2*lat0 + 2*(1-t)*t*ctrl_lat + t**2*lat1
        lon = (1-t)**2*lon0 + 2*(1-t)*t*ctrl_lon + t**2*lon1
        pts.append((lat, lon))
    return pts

def ready_min(charge, target):
    return max(0.0, (target - charge)) * FULL_CHARGE_MIN / 100.0

ORIGIN = (-13.7167, 34.1167)    # Mvera
DEST   = (-13.75961, 34.38926)  # Salima
straight_km = haversine_km(ORIGIN[0], ORIGIN[1], DEST[0], DEST[1])

def init_state():
    if "batteries" not in st.session_state:
        # 4 batteries, varied; middle (3rd) wins on JIT at 85 km leg
        st.session_state.batteries = pd.DataFrame([
            {"id": "BT74 010175", "charge": 95},
            {"id": "BT74 010176", "charge": 87},
            {"id": "BT74 010177", "charge": 85},
            {"id": "BT74 010178", "charge": 99},
        ])
    if "booking" not in st.session_state:
        st.session_state.booking = None
    if "log" not in st.session_state:
        st.session_state.log = []
    if "clock" not in st.session_state:
        st.session_state.clock = 0
    if "counter" not in st.session_state:
        st.session_state.counter = 179

init_state()

def log(kind, msg):
    st.session_state.log.append((st.session_state.clock, kind, msg))

# ---------- sidebar ----------
st.sidebar.header("Trip")
speed = st.sidebar.slider("Average speed (km/h)", 30, 120, int(SPEED))
winding = st.sidebar.slider("Road winding factor (× straight line)", 1.0, 3.0, 1.33, 0.05)
leg_km = st.sidebar.slider("Next leg distance (km)", 20, 150, int(NEXT_LEG_KM))
rest_min = st.sidebar.slider("Estimated rest at station (min)", 0, 60, 15)
swap_min = st.sidebar.slider("Swap time (min)", 0, 15, int(SWAP_MIN))

road_km = straight_km * winding
arrive_min = leg_km / speed * 60.0
depart_min = arrive_min + swap_min + rest_min

with st.sidebar.expander("Edit battery states"):
    for i in st.session_state.batteries.index:
        st.session_state.batteries.loc[i, "charge"] = st.slider(
            f"{st.session_state.batteries.loc[i,'id']}", 0, 100,
            int(st.session_state.batteries.loc[i, "charge"])
        )

# ---------- logic ----------
def scored():
    df = st.session_state.batteries.copy()
    df["ready"] = df["charge"].apply(lambda c: ready_min(c, target=leg_km))
    df["feasible"] = df["charge"] >= leg_km
    df["gap"] = (df["ready"] - arrive_min).abs()
    return df

def best(df):
    f = df[df["feasible"]]
    if f.empty:
        return None
    return f.sort_values("gap").iloc[0]["id"]

def wait_eta(df):
    d = df.copy()
    d["need"] = (leg_km - d["charge"]).clip(lower=0)
    d["wait"] = d["need"] * FULL_CHARGE_MIN / 100.0
    return d.sort_values("wait").iloc[0]

df = scored()
booking = st.session_state.booking

# ---------- itinerary ----------
st.subheader("Itinerary")
st.write(
    f"Mvera → Salima · straight **{straight_km:.1f} km** × winding {winding:.2f} "
    f"= road **{road_km:.1f} km** · at {speed} km/h → arrive **T+{arrive_min:.0f}** · "
    f"swap {swap_min} · rest {rest_min} → depart **T+{depart_min:.0f}**"
)

# ---------- booking ----------
st.subheader("Current booking")
if booking:
    row = df[df["id"] == booking].iloc[0]
    st.success(
        f"**{row['id']}** — {row['charge']}% · ready in {row['ready']:.0f} min · "
        f"you arrive T+{arrive_min:.0f} · gap {row['gap']:.0f} min"
    )
else:
    w = wait_eta(df)
    st.warning(
        f"No feasible battery yet. Earliest: **{w['id']}** reaches "
        f"{leg_km:.0f}% in ~{w['wait']:.0f} min."
    )

# ---------- comparison ----------
st.subheader("Highest-charge rule vs JIT rule")
feasible_df = df[df["feasible"]]
if feasible_df.empty:
    st.caption("No feasible battery to compare.")
else:
    highest = feasible_df.sort_values("charge", ascending=False).iloc[0]
    jit = feasible_df.sort_values("gap").iloc[0]
    comp = pd.DataFrame([
        {"Rule": "Highest charge", "Battery": highest["id"], "Charge %": highest["charge"],
         "Ready (min)": round(highest["ready"], 1), "Gap (min)": round(highest["gap"], 1),
         "Outcome": "Ready too early — wasted readiness"},
        {"Rule": "JIT (ours)", "Battery": jit["id"], "Charge %": jit["charge"],
         "Ready (min)": round(jit["ready"], 1), "Gap (min)": round(jit["gap"], 1),
         "Outcome": "Ready just as you arrive — least waste"},
    ])
    st.dataframe(comp, use_container_width=True, hide_index=True)
    if highest["id"] != jit["id"]:
        st.caption(
            f"JIT picks **{jit['id']}** (gap {jit['gap']:.0f}) instead of "
            f"**{highest['id']}** (gap {highest['gap']:.0f})."
        )

# ---------- batteries (highlighted) ----------
st.subheader("Batteries at station")
b = df.copy()
b["feasible"] = b["feasible"].map({True: "yes", False: "no"})
b = b[["id", "charge", "ready", "gap", "feasible"]].round(1)

def highlight_booked(row):
    if row["id"] == booking:
        return ["background-color: #d4edda; color: #155724; font-weight: bold"] * len(row)
    return [""] * len(row)

st.dataframe(
    b.style.apply(highlight_booked, axis=1),
    use_container_width=True,
    hide_index=True,
)

# ---------- map ----------
st.subheader("Route")
try:
    import folium
    from streamlit_folium import st_folium
    bend = (winding - 1.0) * 0.12
    curve_pts = bezier_curve(ORIGIN, DEST, n=100, bend=bend)
    m = folium.Map(location=[(ORIGIN[0]+DEST[0])/2, (ORIGIN[1]+DEST[1])/2], zoom_start=11)
    folium.Marker(ORIGIN, popup="Mvera (origin)", icon=folium.Icon(color="blue")).add_to(m)
    folium.Marker(DEST, popup="Salima station", icon=folium.Icon(color="green")).add_to(m)
    folium.PolyLine([ORIGIN, DEST], color="gray", weight=2, dash_array="6").add_to(m)
    folium.PolyLine(curve_pts, color="red", weight=4).add_to(m)
    st_folium(m, width=900, height=420)
    st.caption(
        f"Straight {straight_km:.1f} km · winding ×{winding:.2f} → "
        f"estimated road {road_km:.1f} km."
    )
except Exception as e:
    st.info(f"Map not shown: {e}")

# ---------- actions ----------
st.divider()
a1, a2 = st.columns(2)
with a1:
    if st.button("Book best battery", use_container_width=True):
        st.session_state.clock = 0
        st.session_state.log = []
        pick = best(scored())
        st.session_state.booking = pick
        if pick:
            log("book", f"Booked {pick}")
        else:
            w = wait_eta(scored())
            log("wait", f"No feasible battery — wait ~{w['wait']:.0f} min for {w['id']}")
        st.rerun()

with a2:
    with st.popover("Simulate battery arrival"):
        new_charge = st.slider("New battery charge (%)", 50, 100, 92)
        if st.button("Arrive"):
            st.session_state.clock += 10
            new_id = f"BT74 01{st.session_state.counter:04d}"
            st.session_state.counter += 1
            st.session_state.batteries = pd.concat(
                [st.session_state.batteries,
                 pd.DataFrame([{"id": new_id, "charge": new_charge}])],
                ignore_index=True
            )
            log("arrive", f"{new_id} arrived at {new_charge}%")
            old = st.session_state.booking
            new_pick = best(scored())
            if new_pick != old:
                if old:
                    log("flip", f"FLIP → released {old}, now holding {new_pick}")
                else:
                    log("book", f"BOOKED → {new_pick}")
                st.session_state.booking = new_pick
            else:
                log("nochange", f"No change — still {old if old else 'waiting'}")
            st.rerun()

# ---------- log ----------
st.subheader("Event log")
icons = {"book": "✅", "arrive": "📦", "flip": "🔁", "wait": "⏳", "nochange": "•"}
if st.session_state.log:
    for t, kind, msg in st.session_state.log:
        st.markdown(f"`T+{t:03d}` {icons.get(kind,'•')} {msg}")
else:
    st.caption("Book a battery, then simulate an arrival to see flips.")

st.caption(
    f"Leg {leg_km:.0f} km · target {leg_km:.0f}% · full charge {FULL_CHARGE_MIN:.0f} min · "
    f"feasible if charge ≥ {leg_km:.0f}%"
)
