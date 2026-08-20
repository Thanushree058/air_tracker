"""
Air Tracker: Flight Analytics — Streamlit Dashboard

Run:
    streamlit run app.py
"""

from datetime import datetime
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import mysql.connector

from config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
    AIRPORT_CODES,
)


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Air Tracker: Flight Analytics",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# COLORS
# ============================================================

NAVY = "#0B1E39"
BLUE = "#12406B"
SKY = "#1E88E5"
TEAL = "#00B8A9"
AMBER = "#F2A93B"
CORAL = "#F26A6A"
GREY = "#6B778C"
BG = "#F4F7FB"


STATUS_COLORS = {
    "Arrived": TEAL,
    "Departed": SKY,
    "Upcoming": "#7E57C2",
    "Disrupted": AMBER,
    "Unknown": GREY,
}


# ============================================================
# GLOBAL CSS
# ============================================================

st.markdown(
    f"""
    <style>
    .stApp {{
        background: {BG};
    }}

    .main .block-container {{
        padding-top: 1.0rem;
        padding-bottom: 1.5rem;
        padding-left: 1.5rem;
        padding-right: 1.5rem;
        max-width: 1500px;
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #081A33 0%, #0B1E39 100%);
        min-width: 245px !important;
        max-width: 245px !important;
    }}

    section[data-testid="stSidebar"] > div {{
        padding: 1rem 0.85rem;
    }}

    section[data-testid="stSidebar"] * {{
        color: #EAF1FA !important;
    }}

    section[data-testid="stSidebar"] .stRadio > div {{
        gap: 0.25rem;
    }}

    section[data-testid="stSidebar"] .stRadio label {{
        border-radius: 9px;
        padding: 0.52rem 0.55rem;
        font-size: 0.84rem;
        font-weight: 600;
        transition: background 0.15s ease;
    }}

    section[data-testid="stSidebar"] .stRadio label:hover {{
        background: rgba(255,255,255,0.08);
    }}

    /* Hero */
    .hero {{
        background: linear-gradient(115deg, {NAVY} 0%, {BLUE} 58%, {SKY} 100%);
        padding: 1.25rem 1.45rem;
        border-radius: 15px;
        color: white;
        margin-bottom: 1rem;
        box-shadow: 0 7px 20px rgba(11,30,57,0.16);
    }}

    .hero-row {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 1rem;
    }}

    .hero h1 {{
        margin: 0;
        font-size: 1.55rem;
        font-weight: 800;
        letter-spacing: -0.2px;
    }}

    .hero p {{
        margin: 0.35rem 0 0;
        opacity: 0.86;
        font-size: 0.80rem;
        line-height: 1.45;
    }}

    .live-pill {{
        white-space: nowrap;
        padding: 0.34rem 0.62rem;
        border-radius: 999px;
        background: rgba(255,255,255,0.12);
        border: 1px solid rgba(255,255,255,0.20);
        font-size: 0.70rem;
        font-weight: 700;
    }}

    /* Section headings */
    .section-title {{
        display: flex;
        align-items: center;
        gap: 0.45rem;
        font-size: 0.96rem;
        font-weight: 750;
        color: {NAVY};
        margin: 0.85rem 0 0.45rem;
    }}

    .section-subtitle {{
        color: {GREY};
        font-size: 0.72rem;
        margin: -0.25rem 0 0.45rem;
    }}

    /* KPI cards */
    .kpi {{
        background: #FFFFFF;
        border: 1px solid #E4EAF3;
        border-radius: 12px;
        padding: 0.75rem 0.85rem;
        min-height: 82px;
        box-shadow: 0 2px 9px rgba(11,30,57,0.055);
    }}

    .kpi-label {{
        color: {GREY};
        font-size: 0.70rem;
        font-weight: 650;
        text-transform: uppercase;
        letter-spacing: 0.35px;
    }}

    .kpi-value {{
        color: {NAVY};
        font-size: 1.42rem;
        line-height: 1.15;
        font-weight: 800;
        margin-top: 0.22rem;
    }}

    .kpi-note {{
        color: #8995A7;
        font-size: 0.66rem;
        margin-top: 0.18rem;
    }}

    /* Cards around charts/tables */
    .panel {{
        background: white;
        border: 1px solid #E4EAF3;
        border-radius: 13px;
        padding: 0.25rem 0.35rem 0.05rem;
        box-shadow: 0 2px 9px rgba(11,30,57,0.045);
    }}

    .status-summary {{
        display: flex;
        gap: 0.45rem;
        flex-wrap: wrap;
        margin-top: 0.25rem;
    }}

    .status-chip {{
        border: 1px solid #E6EBF2;
        border-radius: 8px;
        padding: 0.32rem 0.5rem;
        background: #FAFBFD;
        font-size: 0.67rem;
        color: #536176;
    }}

    .status-chip strong {{
        color: {NAVY};
    }}

    /* Streamlit components */
    div[data-testid="stDataFrame"] {{
        border-radius: 10px;
        overflow: hidden;
    }}

    .stButton > button {{
        border-radius: 8px;
        font-weight: 650;
    }}

    button[data-baseweb="tab"] {{
        font-weight: 650;
    }}

    footer {{
        visibility: hidden;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# DATABASE CONNECTION
# ============================================================

def get_connection():
    """
    Connect to MySQL using values loaded from config.py/.env.
    """

    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


# ============================================================
# QUERY FUNCTION
# ============================================================

@st.cache_data(ttl=120, show_spinner=False)
def q(sql, params=None):
    """
    Execute SQL and return a DataFrame.
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()

        cursor = conn.cursor(
            dictionary=True
        )

        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(
                sql,
                params
            )

        rows = cursor.fetchall()

        return pd.DataFrame(rows)

    finally:

        if cursor is not None:
            cursor.close()

        if conn is not None:
            conn.close()


# ============================================================
# TABLE CLEANUP
# ============================================================

def tidy(df, rename=None):

    if df.empty:
        return df

    out = df.copy()

    out = out.fillna("—")

    out = out.replace(
        {
            "NA": "—",
            "NaN": "—",
            "nan": "—",
            "None": "—",
            "": "—",
        }
    )

    if rename:
        out = out.rename(
            columns=rename
        )

    return out


# ============================================================
# UI HELPERS
# ============================================================

def hero(title, subtitle, updated_text=None):
    updated_text = updated_text or f"Updated {datetime.now().strftime('%d %b %Y, %H:%M')}"
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-row">
                <div>
                    <h1>✈️ {title}</h1>
                    <p>{subtitle}</p>
                </div>
                <div class="live-pill">● {updated_text}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title, subtitle=None):
    st.markdown(
        f"""
        <div class="section-title">{title}</div>
        {f'<div class="section-subtitle">{subtitle}</div>' if subtitle else ''}
        """,
        unsafe_allow_html=True,
    )


def kpi(label, value, note=""):
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            {f'<div class="kpi-note">{note}</div>' if note else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


AIRLINE_NAMES = {
    "DL": "Delta Air Lines",
    "AA": "American Airlines",
    "LH": "Lufthansa",
    "BA": "British Airways",
    "6E": "IndiGo",
    "UA": "United Airlines",
    "NH": "All Nippon Airways",
    "EK": "Emirates",
    "SQ": "Singapore Airlines",
    "IB": "Iberia",
    "KL": "KLM",
    "AF": "Air France",
    "QR": "Qatar Airways",
    "AI": "Air India",
    "QF": "Qantas",
    "JL": "Japan Airlines",
}


def airline_label(code):
    code = str(code)
    return f"{AIRLINE_NAMES.get(code, code)} ({code})"


def clean_status(status):
    status = str(status)
    if status in {"Expected", "Approaching", "CheckIn", "GateClosed", "Scheduled", "Boarding"}:
        return "Upcoming"
    if status in {"Canceled", "Cancelled", "CancelledUncertain", "Delayed"}:
        return "Disrupted"
    if status in {"Arrived", "Departed"}:
        return status
    return "Unknown"


STATUS_GROUPS = {
    "Arrived": {"Arrived"},
    "Departed": {"Departed"},
    "Upcoming": {"Expected", "Approaching", "CheckIn", "GateClosed", "Scheduled", "Boarding"},
    "Disrupted": {"Canceled", "Cancelled", "CancelledUncertain", "Delayed"},
    "Unknown": {"Unknown", "None", "nan"},
}


def status_filter_values(display_status):
    return sorted(STATUS_GROUPS.get(display_status, {display_status}))


def apply_display_status(df, column="status"):
    if column in df.columns:
        df = df.copy()
        df[column] = df[column].apply(clean_status)
    return df


def format_datetime_columns(df, columns):
    out = df.copy()
    for column in columns:
        if column in out.columns:
            parsed = pd.to_datetime(out[column], errors="coerce")
            out[column] = parsed.dt.strftime("%d %b · %H:%M")
            out[column] = out[column].fillna("—")
    return out


def format_airline_column(df, column="airline_code"):
    out = df.copy()
    if column in out.columns:
        out[column] = out[column].apply(
            lambda code: "—" if pd.isna(code) else airline_label(code)
        )
    return out


def reset_search_filters():
    for key, value in {
        "search_flight_number": "",
        "search_airline": "All",
        "search_status": "All",
        "search_origin": "All",
        "search_destination": "All",
        "search_date_range": (SEARCH_MIN_DATE, SEARCH_MAX_DATE),
    }.items():
        st.session_state[key] = value


# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## ✈️ Air Tracker")
    st.caption("FLIGHT ANALYTICS CONSOLE")
    st.divider()

    st.markdown(
        '<div style="font-size:0.66rem;color:#91A0B7;font-weight:700;letter-spacing:0.7px;margin-bottom:0.25rem;">OVERVIEW</div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Navigate",
        [
            "🏠  Homepage",
            "🔎  Search & Filter Flights",
            "🛫  Airport Details",
            "⏱️  Delay Analysis",
            "🏆  Route Leaderboards",
        ],
        label_visibility="collapsed",
    )

    page = page.split("  ", 1)[1]

    st.divider()

    st.markdown(
        '<div style="font-size:0.66rem;color:#91A0B7;font-weight:700;letter-spacing:0.7px;margin-bottom:0.35rem;">DATA SOURCE</div>',
        unsafe_allow_html=True,
    )
    st.caption("AeroDataBox API")
    st.caption(f"MySQL · {DB_NAME}")
    st.caption(f"{len(AIRPORT_CODES)} airports monitored")

    st.write("")
    if st.button("↻  Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# HOMEPAGE
# ============================================================

if page == "Homepage":

    hero(
        "Air Tracker: Flight Analytics",
        (
            f"Operational flight intelligence across {len(AIRPORT_CODES)} monitored airports, "
            "combining AeroDataBox data with MySQL-backed analytics."
        ),
    )

    # ---------------- KPI DATA ----------------
    total_airports = len(AIRPORT_CODES)

    total_flights_df = q("SELECT COUNT(*) AS n FROM flights")
    total_flights = int(total_flights_df.iloc[0]["n"]) if not total_flights_df.empty else 0

    total_aircraft_df = q(
        """
        SELECT COUNT(DISTINCT ac.registration) AS n
        FROM aircraft ac
        JOIN flights f ON f.aircraft_registration = ac.registration
        WHERE ac.model IS NOT NULL
        """
    )
    total_aircraft = int(total_aircraft_df.iloc[0]["n"]) if not total_aircraft_df.empty else 0

    total_airlines_df = q(
        """
        SELECT COUNT(DISTINCT airline_code) AS n
        FROM flights
        WHERE airline_code IS NOT NULL
        """
    )
    total_airlines = int(total_airlines_df.iloc[0]["n"]) if not total_airlines_df.empty else 0

    avg_delay_df = q(
        """
        SELECT AVG(avg_delay_min) AS n
        FROM airport_delays
        WHERE avg_delay_min IS NOT NULL
          AND delay_date = (SELECT MAX(delay_date) FROM airport_delays)
        """
    )
    avg_delay = None
    if not avg_delay_df.empty and pd.notna(avg_delay_df.iloc[0]["n"]):
        avg_delay = float(avg_delay_df.iloc[0]["n"])

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        kpi("Airports monitored", f"{total_airports:,}", "Network coverage")
    with k2:
        kpi("Total flights", f"{total_flights:,}", "Flights in database")
    with k3:
        kpi("Tracked aircraft", f"{total_aircraft:,}", "Referenced by flights")
    with k4:
        kpi("Airlines", f"{total_airlines:,}", "Unique airline codes")
    with k5:
        kpi("Average delay", f"{avg_delay:.1f} min" if avg_delay is not None else "—", "Latest delay snapshot")

    # ---------------- MAP + STATUS ----------------
    left, right = st.columns([1.35, 1])

    with left:
        section(
            "🗺️ Airport Network",
            "Flight activity across the monitored airport network",
        )

        geo = q(
            """
            SELECT iata_code, name, city, latitude, longitude
            FROM airport
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            """
        )

        if not geo.empty:
            flight_counts = q(
                """
                SELECT origin_iata AS iata_code, COUNT(*) AS flights
                FROM flights
                WHERE origin_iata IS NOT NULL
                GROUP BY origin_iata
                """
            )

            geo = geo.merge(flight_counts, on="iata_code", how="left")
            geo["flights"] = geo["flights"].fillna(0)
            geo["latitude"] = geo["latitude"].astype(float)
            geo["longitude"] = geo["longitude"].astype(float)

            # scatter_geo avoids the repeated world-map wrapping seen
            # with mapbox when the monitored airports span the globe.
            fig_map = px.scatter_geo(
                geo,
                lat="latitude",
                lon="longitude",
                size=geo["flights"] + 20,
                color="flights",
                color_continuous_scale="Tealgrn",
                hover_name="name",
                hover_data={
                    "iata_code": True,
                    "city": True,
                    "flights": True,
                    "latitude": False,
                    "longitude": False,
                },
            )

            fig_map.update_traces(
                marker=dict(
                    opacity=0.82,
                    line=dict(width=1, color="white"),
                )
            )

            fig_map.update_geos(
                showland=True,
                landcolor="#DCE3E7",
                showocean=True,
                oceancolor="#F7F9FB",
                showcountries=True,
                countrycolor="#C7CFD8",
                showcoastlines=False,
                projection_type="equirectangular",
                projection_scale=1.0,
                center=dict(lat=18, lon=15),
                lataxis_showgrid=False,
                lonaxis_showgrid=False,
            )

            fig_map.update_layout(
                height=380,
                margin=dict(l=0, r=0, t=0, b=0),
                coloraxis_colorbar=dict(
                    title="Flights",
                    thickness=10,
                    len=0.65,
                ),
                paper_bgcolor="white",
                plot_bgcolor="white",
            )

            st.plotly_chart(fig_map, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No geolocated airports available.")

    with right:
        section(
            "✈️ Flight Status Overview",
            "High-level operational status of tracked flights",
        )

        status_df = q(
            """
            SELECT status, COUNT(*) AS count
            FROM flights
            WHERE status IS NOT NULL
            GROUP BY status
            """
        )

        if not status_df.empty:
            status_df["category"] = status_df["status"].apply(clean_status)
            grouped = (
                status_df.groupby("category", as_index=False)["count"]
                .sum()
                .sort_values("count", ascending=False)
            )

            category_colors = {
                "Arrived": TEAL,
                "Departed": SKY,
                "Upcoming": "#7E57C2",
                "Disrupted": AMBER,
                "Unknown": GREY,
            }

            fig = px.pie(
                grouped,
                names="category",
                values="count",
                hole=0.62,
                color="category",
                color_discrete_map=category_colors,
            )

            fig.update_traces(
                textinfo="percent",
                hovertemplate="<b>%{label}</b><br>%{value:,} flights<br>%{percent}<extra></extra>",
                marker=dict(line=dict(color="white", width=2)),
            )

            fig.update_layout(
                height=315,
                margin=dict(l=0, r=0, t=0, b=0),
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.04,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=10),
                ),
                paper_bgcolor="white",
                plot_bgcolor="white",
            )

            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            chips = []
            for _, row in grouped.iterrows():
                pct = row["count"] / grouped["count"].sum() * 100
                chips.append(
                    f'<div class="status-chip"><strong>{row["category"]}</strong> · {pct:.1f}%</div>'
                )
            st.markdown(
                '<div class="status-summary">' + "".join(chips) + "</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                "Status labels are standardized across the dashboard. "
                "Upcoming groups expected/approaching/ground-operation states; "
                "Disrupted groups delayed/cancelled states."
            )
        else:
            st.info("No flight status data available.")

    # ---------------- AIRLINES + RECENT ----------------
    left2, right2 = st.columns([1.35, 1])

    with left2:
        section(
            "🏢 Top 10 Airlines by Flight Volume",
            "Airlines with the highest number of tracked flights",
        )

        airline_df = q(
            """
            SELECT airline_code, COUNT(*) AS total_flights
            FROM flights
            WHERE airline_code IS NOT NULL
            GROUP BY airline_code
            ORDER BY total_flights DESC
            LIMIT 10
            """
        )

        if not airline_df.empty:
            chart_df = airline_df.sort_values("total_flights").copy()
            chart_df["airline"] = chart_df["airline_code"].apply(airline_label)

            fig = px.bar(
                chart_df,
                x="total_flights",
                y="airline",
                orientation="h",
                text="total_flights",
            )

            fig.update_traces(
                marker_color=SKY,
                texttemplate="%{text:,}",
                textposition="outside",
                cliponaxis=False,
            )

            fig.update_layout(
                height=350,
                margin=dict(l=0, r=35, t=5, b=0),
                xaxis_title="Flights",
                yaxis_title="",
                showlegend=False,
                paper_bgcolor="white",
                plot_bgcolor="white",
                xaxis=dict(showgrid=True, gridcolor="#EDF1F5", zeroline=False),
                yaxis=dict(showgrid=False),
            )

            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No airline data available.")

    with right2:
        section(
            "🕓 Recent Flight Activity",
            "Latest flights with confirmed departure or arrival activity",
        )

        recent = q(
            """
            SELECT
                flight_number,
                origin_iata,
                destination_iata,
                status,
                actual_arrival,
                actual_departure,
                COALESCE(actual_arrival, actual_departure) AS latest_time
            FROM flights
            WHERE flight_number IS NOT NULL
              AND (actual_arrival IS NOT NULL OR actual_departure IS NOT NULL)
            ORDER BY COALESCE(actual_arrival, actual_departure) DESC
            LIMIT 8
            """
        )

        if not recent.empty:
            recent["Route"] = (
                recent["origin_iata"].astype(str)
                + " → "
                + recent["destination_iata"].astype(str)
            )

            recent_view = recent[
                ["flight_number", "Route", "status", "latest_time"]
            ].copy()

            # Derive the shown status from the timestamp that got
            # this row selected, not the (possibly stale) status
            # text, so it can't contradict the "confirmed activity"
            # caption above.
            recent_view["status"] = [
                "Arrived" if pd.notna(arr)
                else "Departed" if pd.notna(dep)
                else clean_status(s)
                for arr, dep, s in zip(
                    recent["actual_arrival"],
                    recent["actual_departure"],
                    recent["status"],
                )
            ]

            st.dataframe(
                tidy(
                    recent_view,
                    {
                        "flight_number": "Flight",
                        "status": "Status",
                        "latest_time": "Updated",
                    },
                ),
                use_container_width=True,
                hide_index=True,
                height=350,
                column_config={
                    "Flight": st.column_config.TextColumn("Flight", width="small"),
                    "Route": st.column_config.TextColumn("Route", width="medium"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Updated": st.column_config.DatetimeColumn(
                        "Updated",
                        format="DD MMM · HH:mm",
                    ),
                },
            )
        else:
            st.info("No recent flight activity found.")

    st.caption(
        "Homepage is designed as an overview: use Search & Filter Flights, Airport Details, "
        "Delay Analysis, and Route Leaderboards for deeper investigation."
    )


# SEARCH & FILTER FLIGHTS
# ============================================================

elif page == "Search & Filter Flights":

    hero(
        "Search & Filter Flights",
        "Search and filter flights by airline, status, route, flight number, or date.",
    )

    # --------------------------------------------------------
    # FILTER OPTIONS
    # --------------------------------------------------------

    airline_df = q(
        """
        SELECT DISTINCT airline_code
        FROM flights
        WHERE airline_code IS NOT NULL
        ORDER BY airline_code
        """
    )
    airlines = airline_df["airline_code"].tolist() if not airline_df.empty else []

    airline_options = ["All"] + [airline_label(code) for code in airlines]
    airline_lookup = {airline_label(code): code for code in airlines}

    statuses = ["Arrived", "Departed", "Disrupted", "Unknown", "Upcoming"]

    origin_df = q(
        """
        SELECT DISTINCT origin_iata
        FROM flights
        WHERE origin_iata IS NOT NULL
        ORDER BY origin_iata
        """
    )
    origins = origin_df["origin_iata"].tolist() if not origin_df.empty else []

    destination_df = q(
        """
        SELECT DISTINCT destination_iata
        FROM flights
        WHERE destination_iata IS NOT NULL
        ORDER BY destination_iata
        """
    )
    destinations = destination_df["destination_iata"].tolist() if not destination_df.empty else []

    date_bounds = q(
        """
        SELECT
            MIN(scheduled_departure) AS min_date,
            MAX(scheduled_departure) AS max_date
        FROM flights
        WHERE scheduled_departure IS NOT NULL
        """
    )

    if not date_bounds.empty and pd.notna(date_bounds.iloc[0]["min_date"]):
        SEARCH_MIN_DATE = pd.to_datetime(date_bounds.iloc[0]["min_date"]).date()
        SEARCH_MAX_DATE = pd.to_datetime(date_bounds.iloc[0]["max_date"]).date()
    else:
        SEARCH_MIN_DATE = datetime.now().date()
        SEARCH_MAX_DATE = datetime.now().date()

    if "search_date_range" not in st.session_state:
        st.session_state["search_date_range"] = (SEARCH_MIN_DATE, SEARCH_MAX_DATE)

    section("Filters", "Use any combination of filters. Date range uses scheduled departure date.")

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)

        flight_number = c1.text_input(
            "Flight number contains",
            placeholder="e.g. AI 505",
            key="search_flight_number",
        )

        airline_filter = c2.selectbox(
            "Airline",
            airline_options,
            key="search_airline",
        )

        status_filter = c3.selectbox(
            "Status",
            ["All"] + statuses,
            key="search_status",
        )

        c4, c5, c6 = st.columns(3)

        origin_filter = c4.selectbox(
            "Origin",
            ["All"] + sorted(origins),
            key="search_origin",
        )

        destination_filter = c5.selectbox(
            "Destination",
            ["All"] + sorted(destinations),
            key="search_destination",
        )

        date_range = c6.date_input(
            "Departure date range",
            min_value=SEARCH_MIN_DATE,
            max_value=SEARCH_MAX_DATE,
            key="search_date_range",
        )

        clear_col, _ = st.columns([1, 5])
        clear_col.button(
            "↺ Clear filters",
            key="clear_search_filters",
            on_click=reset_search_filters,
            use_container_width=True,
        )

    # Streamlit returns a tuple for a date-range input and a single date
    # if the user temporarily selects only one endpoint.
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range

    sql = """
        SELECT
            flight_number,
            aircraft_registration,
            origin_iata,
            destination_iata,
            scheduled_departure,
            actual_departure,
            scheduled_arrival,
            actual_arrival,
            status,
            airline_code
        FROM flights
        WHERE 1 = 1
    """

    params = []

    if flight_number:
        sql += " AND flight_number LIKE %s"
        params.append(f"%{flight_number}%")

    if airline_filter != "All":
        sql += " AND airline_code = %s"
        params.append(airline_lookup[airline_filter])

    if status_filter != "All":
        raw_statuses = status_filter_values(status_filter)
        placeholders = ", ".join(["%s"] * len(raw_statuses))
        sql += f" AND status IN ({placeholders})"
        params.extend(raw_statuses)

    if origin_filter != "All":
        sql += " AND origin_iata = %s"
        params.append(origin_filter)

    if destination_filter != "All":
        sql += " AND destination_iata = %s"
        params.append(destination_filter)

    # Include the complete end date by using a half-open interval.
    if start_date:
        sql += " AND scheduled_departure >= %s"
        params.append(datetime.combine(start_date, datetime.min.time()))

    if end_date:
        next_day = end_date + pd.Timedelta(days=1)
        sql += " AND scheduled_departure < %s"
        params.append(datetime.combine(next_day, datetime.min.time()))

    where_part = sql.split("WHERE 1 = 1", 1)[1]

    count_sql = "SELECT COUNT(*) AS n FROM flights WHERE 1 = 1" + where_part
    count_df = q(count_sql, tuple(params))
    total_matches = int(count_df.iloc[0]["n"]) if not count_df.empty else 0

    sql += " ORDER BY scheduled_departure DESC LIMIT 500"
    results = q(sql, tuple(params))

    section("Flight Results")
    st.caption(
        f"{total_matches:,} flights found · Showing first {min(total_matches, 500):,} results. "
        "— indicates information has not been reported yet."
    )

    if results.empty:
        st.info("No flights match the selected filters. Try widening the date range or clearing a filter.")
    else:
        results = apply_display_status(results)
        results = format_datetime_columns(
            results,
            [
                "scheduled_departure",
                "actual_departure",
                "scheduled_arrival",
                "actual_arrival",
            ],
        )
        results = format_airline_column(results)

        display_results = tidy(
            results,
            {
                "flight_number": "Flight",
                "aircraft_registration": "Aircraft Reg.",
                "origin_iata": "Origin",
                "destination_iata": "Destination",
                "scheduled_departure": "Sched. Departure",
                "actual_departure": "Actual Departure",
                "scheduled_arrival": "Sched. Arrival",
                "actual_arrival": "Actual Arrival",
                "status": "Status",
                "airline_code": "Airline",
            },
        )

        st.dataframe(
            display_results,
            use_container_width=True,
            height=520,
            hide_index=True,
            column_config={
                "Flight": st.column_config.TextColumn("Flight", width="small"),
                "Aircraft Reg.": st.column_config.TextColumn("Aircraft", width="small"),
                "Origin": st.column_config.TextColumn("From", width="small"),
                "Destination": st.column_config.TextColumn("To", width="small"),
                "Sched. Departure": st.column_config.TextColumn("Sched. Departure", width="medium"),
                "Actual Departure": st.column_config.TextColumn("Actual Departure", width="medium"),
                "Sched. Arrival": st.column_config.TextColumn("Sched. Arrival", width="medium"),
                "Actual Arrival": st.column_config.TextColumn("Actual Arrival", width="medium"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Airline": st.column_config.TextColumn("Airline", width="medium"),
            },
        )

        st.download_button(
            "⬇️ Download filtered results as CSV",
            data=display_results.to_csv(index=False).encode("utf-8"),
            file_name="air_tracker_filtered_flights.csv",
            mime="text/csv",
        )


# AIRPORT DETAILS
# ============================================================

elif page == "Airport Details":

    hero(
        "Airport Details",
        (
            "Explore location, timezone, and flight activity "
            "for airports in the database."
        ),
    )

    airports = q(
        """
        SELECT
            iata_code,
            icao_code,
            name,
            city,
            country,
            continent,
            latitude,
            longitude,
            timezone,
            (
                icao_code IS NOT NULL
                AND name <> iata_code
            ) AS has_full_data
        FROM airport
        ORDER BY
            has_full_data DESC,
            name IS NULL,
            name
        """
    )

    if airports.empty:

        st.info(
            "No airport data available."
        )

    else:

        only_full = st.toggle(
            "Show only fully-fetched airports",
            value=True,
        )

        view = (
            airports[
                airports["has_full_data"] == 1
            ]
            if only_full
            else airports
        )

        if view.empty:

            st.warning(
                "No fully-fetched airports found."
            )

        else:

            labels = (
                view["iata_code"]
                + " — "
                + view["name"].fillna(
                    "Unknown Airport"
                )
            )

            choice = st.selectbox(
                "Select airport",
                labels,
            )

            iata = choice.split(
                " — ",
                1
            )[0]

            details = (
                airports[
                    airports["iata_code"] == iata
                ]
                .iloc[0]
            )

            # ------------------------------------------------
            # FIXED AIRPORT NAME LOGIC
            # ------------------------------------------------

            airport_name = (
                details["name"]
                if pd.notna(details["name"])
                else iata
            )

            city = (
                details["city"]
                if pd.notna(details["city"])
                else "—"
            )

            country = (
                details["country"]
                if pd.notna(details["country"])
                else "—"
            )

            timezone = (
                details["timezone"]
                if pd.notna(details["timezone"])
                else "—"
            )

            c1, c2, c3 = st.columns(
                [1.4, 1, 1]
            )

            with c1:

                st.markdown(
                    f"### {airport_name}"
                )

                caption = (
                    f"{city}, {country}"
                    f" · IATA `{details['iata_code']}`"
                )

                if pd.notna(
                    details["icao_code"]
                ):

                    caption += (
                        f" · ICAO "
                        f"`{details['icao_code']}`"
                    )

                st.caption(
                    caption
                )

                st.caption(
                    f"Timezone: {timezone}"
                )

            dep_count = q(
                """
                SELECT COUNT(*) AS n
                FROM flights
                WHERE origin_iata = %s
                """,
                (iata,),
            )

            dep_count = int(
                dep_count.iloc[0]["n"]
            )

            arr_count = q(
                """
                SELECT COUNT(*) AS n
                FROM flights
                WHERE destination_iata = %s
                """,
                (iata,),
            )

            arr_count = int(
                arr_count.iloc[0]["n"]
            )

            with c2:

                st.metric(
                    "Departures",
                    dep_count,
                )

            with c3:

                st.metric(
                    "Arrivals",
                    arr_count,
                )

            # ------------------------------------------------
            # AIRPORT MAP
            # ------------------------------------------------

            if (
                pd.notna(details["latitude"])
                and pd.notna(details["longitude"])
            ):

                fig_map = go.Figure(
                    go.Scattermapbox(
                        lat=[
                            details["latitude"]
                        ],
                        lon=[
                            details["longitude"]
                        ],
                        mode="markers",
                        marker=dict(
                            size=16,
                            color=CORAL,
                        ),
                        text=[
                            airport_name
                        ],
                    )
                )

                fig_map.update_layout(
                    mapbox=dict(
                        style="carto-positron",
                        center=dict(
                            lat=float(
                                details["latitude"]
                            ),
                            lon=float(
                                details["longitude"]
                            ),
                        ),
                        zoom=8,
                    ),
                    margin=dict(
                        l=0,
                        r=0,
                        t=0,
                        b=0,
                    ),
                    height=260,
                )

                st.plotly_chart(
                    fig_map,
                    use_container_width=True,
                )

            tab1, tab2 = st.tabs(
                [
                    "🛫 Departures",
                    "🛬 Arrivals",
                ]
            )

            # ------------------------------------------------
            # DEPARTURES
            # ------------------------------------------------

            with tab1:

                departures = q(
                    """
                    SELECT
                        flight_number,
                        aircraft_registration,
                        destination_iata,
                        scheduled_departure,
                        actual_departure,
                        status,
                        airline_code
                    FROM flights
                    WHERE origin_iata = %s
                    ORDER BY scheduled_departure DESC
                    LIMIT 200
                    """,
                    (iata,),
                )

                if departures.empty:

                    st.info(
                        "No departure records available."
                    )

                else:

                    departures = apply_display_status(departures)

                    st.dataframe(
                        tidy(
                            departures,
                            {
                                "flight_number": "Flight",
                                "aircraft_registration": "Aircraft",
                                "destination_iata": "Destination",
                                "scheduled_departure": "Sched. Departure",
                                "actual_departure": "Actual Departure",
                                "status": "Status",
                                "airline_code": "Airline",
                            },
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

            # ------------------------------------------------
            # ARRIVALS
            # ------------------------------------------------

            with tab2:

                arrivals = q(
                    """
                    SELECT
                        flight_number,
                        aircraft_registration,
                        origin_iata,
                        scheduled_arrival,
                        actual_arrival,
                        status,
                        airline_code
                    FROM flights
                    WHERE destination_iata = %s
                    ORDER BY scheduled_arrival DESC
                    LIMIT 200
                    """,
                    (iata,),
                )

                if arrivals.empty:

                    st.info(
                        "No arrival records available."
                    )

                else:

                    arrivals = apply_display_status(arrivals)

                    st.dataframe(
                        tidy(
                            arrivals,
                            {
                                "flight_number": "Flight",
                                "aircraft_registration": "Aircraft",
                                "origin_iata": "Origin",
                                "scheduled_arrival": "Sched. Arrival",
                                "actual_arrival": "Actual Arrival",
                                "status": "Status",
                                "airline_code": "Airline",
                            },
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )


# ============================================================
# DELAY ANALYSIS
# ============================================================

elif page == "Delay Analysis":

    hero(
        "Delay Analysis",
        (
            "Delay counts and cancellation rates captured "
            "from AeroDataBox airport delay information."
        ),
    )

    delays = q(
        """
        SELECT
            ad.airport_iata,
            a.name,
            ad.avg_delay_min,
            ad.median_delay_min,
            ad.delayed_flights,
            ad.total_flights,
            ad.canceled_flights
        FROM airport_delays ad
        LEFT JOIN airport a
            ON a.iata_code = ad.airport_iata
        WHERE ad.delay_date = (SELECT MAX(delay_date) FROM airport_delays)
        ORDER BY ad.delayed_flights DESC
        """
    )

    if delays.empty:

        st.warning(
            "No airport delay data is currently available."
        )

        st.info(
            "Your flight and airport data are still available. "
            "Some AeroDataBox airports may not provide live "
            "delay information."
        )

    else:

        delays["pct_delayed"] = (
            100
            * delays["delayed_flights"]
            / delays["total_flights"].replace(
                0,
                pd.NA,
            )
        ).round(2)

        delays["label"] = (
            delays["name"].fillna(
                delays["airport_iata"]
            )
        )

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Airports with delay data",
            len(delays),
        )

        c2.metric(
            "Total flights captured",
            int(
                delays["total_flights"].sum()
            ),
            help=(
                "Sum of each monitored airport's own flight count. "
                "A flight between two monitored airports (e.g. "
                "LHR ↔ FRA) is counted once per airport touched, so "
                "this total runs higher than the Homepage's unique "
                "flight count."
            ),
        )

        avg_pct = delays[
            "pct_delayed"
        ].mean()

        c3.metric(
            "Avg % delayed",
            (
                f"{avg_pct:.1f}%"
                if pd.notna(avg_pct)
                else "—"
            ),
        )

        left, right = st.columns(2)

        with left:

            section(
                "⏱️ Delayed Flight Counts by Airport"
            )

            fig1 = px.bar(
                delays.sort_values(
                    "delayed_flights"
                ),
                x="delayed_flights",
                y="label",
                orientation="h",
                color="delayed_flights",
                color_continuous_scale="Oranges",
            )

            fig1.update_layout(
                template="plotly_white",
                coloraxis_showscale=False,
                margin=dict(
                    l=0,
                    r=10,
                    t=5,
                    b=0,
                ),
                height=420,
                yaxis_title="",
                xaxis_title="Delayed flights",
            )

            st.plotly_chart(
                fig1,
                use_container_width=True,
            )

        with right:

            section(
                "📉 % of Flights Delayed by Airport"
            )

            fig2 = px.bar(
                delays.sort_values(
                    "pct_delayed"
                ),
                x="pct_delayed",
                y="label",
                orientation="h",
                color="pct_delayed",
                color_continuous_scale="Reds",
            )

            fig2.update_layout(
                template="plotly_white",
                coloraxis_showscale=False,
                margin=dict(
                    l=0,
                    r=10,
                    t=5,
                    b=0,
                ),
                height=420,
                yaxis_title="",
                xaxis_title="% delayed",
            )

            st.plotly_chart(
                fig2,
                use_container_width=True,
            )

        section(
            "📋 Full Delay Snapshot"
        )

        st.caption(
            "Avg/Median Delay show as blank for airports where "
            "fewer than 5 flights had both a scheduled and actual "
            "time recorded - not enough data for a reliable average, "
            "so we don't show a number instead of guessing."
        )

        st.dataframe(
            tidy(
                delays.drop(
                    columns=["label"]
                ),
                {
                    "airport_iata": "Airport",
                    "name": "Name",
                    "avg_delay_min": "Avg Delay (min)",
                    "median_delay_min": "Median Delay (min)",
                    "delayed_flights": "Delayed",
                    "total_flights": "Total",
                    "canceled_flights": "Canceled",
                    "pct_delayed": "% Delayed",
                },
            ),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# ROUTE LEADERBOARDS
# ============================================================

elif page == "Route Leaderboards":

    hero(
        "Route Leaderboards",
        (
            "The busiest routes, airports, and aircraft "
            "models in the network."
        ),
    )

    # --------------------------------------------------------
    # BUSIEST ROUTES
    # --------------------------------------------------------

    busiest = q(
        """
        SELECT
            o.name AS origin_name,
            f.origin_iata,
            d.name AS dest_name,
            f.destination_iata,
            COUNT(*) AS flight_count
        FROM flights f
        JOIN airport o
            ON o.iata_code = f.origin_iata
        JOIN airport d
            ON d.iata_code = f.destination_iata
        WHERE f.origin_iata IS NOT NULL
          AND f.destination_iata IS NOT NULL
        GROUP BY
            o.name,
            f.origin_iata,
            d.name,
            f.destination_iata
        ORDER BY flight_count DESC
        LIMIT 10
        """
    )

    section(
        "✈️ Busiest Routes"
    )

    if busiest.empty:

        st.warning(
            "No complete origin-destination routes available."
        )

    else:

        busiest["route"] = (
            busiest["origin_iata"]
            + " → "
            + busiest["destination_iata"]
        )

        fig3 = px.bar(
            busiest.sort_values(
                "flight_count"
            ),
            x="flight_count",
            y="route",
            orientation="h",
            text="flight_count",
            color="flight_count",
            color_continuous_scale="Teal",
        )

        fig3.update_layout(
            template="plotly_white",
            coloraxis_showscale=False,
            margin=dict(
                l=0,
                r=10,
                t=5,
                b=0,
            ),
            height=420,
            yaxis_title="",
            xaxis_title="Flights",
        )

        st.plotly_chart(
            fig3,
            use_container_width=True,
        )

        st.dataframe(
            tidy(
                busiest[
                    [
                        "origin_iata",
                        "origin_name",
                        "destination_iata",
                        "dest_name",
                        "flight_count",
                    ]
                ],
                {
                    "origin_iata": "Origin",
                    "origin_name": "Origin Airport",
                    "destination_iata": "Destination",
                    "dest_name": "Destination Airport",
                    "flight_count": "Flights",
                },
            ),
            use_container_width=True,
            hide_index=True,
        )

    # ========================================================
    # TOP DEPARTURES / ARRIVALS
    # ========================================================

    left, right = st.columns(2)

    # --------------------------------------------------------
    # DEPARTURES
    # --------------------------------------------------------

    with left:

        section(
            "🛫 Top Airports by Departures"
        )

        departures = q(
            """
            SELECT
                a.name,
                f.origin_iata AS airport,
                COUNT(*) AS departures
            FROM flights f
            LEFT JOIN airport a
                ON a.iata_code = f.origin_iata
            WHERE f.origin_iata IS NOT NULL
            GROUP BY
                a.name,
                f.origin_iata
            ORDER BY departures DESC
            LIMIT 10
            """
        )

        if not departures.empty:

            departures["label"] = (
                departures["airport"]
                + " · "
                + departures["name"].fillna(
                    "Unknown"
                )
            )

            fig4 = px.bar(
                departures.sort_values(
                    "departures"
                ),
                x="departures",
                y="label",
                orientation="h",
                color="departures",
                color_continuous_scale="Blues",
            )

            fig4.update_layout(
                template="plotly_white",
                coloraxis_showscale=False,
                margin=dict(
                    l=0,
                    r=10,
                    t=5,
                    b=0,
                ),
                height=380,
                yaxis_title="",
                xaxis_title="Departures",
            )

            st.plotly_chart(
                fig4,
                use_container_width=True,
            )

        else:

            st.info(
                "No departure data available."
            )

    # --------------------------------------------------------
    # ARRIVALS
    # --------------------------------------------------------

    with right:

        section(
            "🛬 Top Airports by Arrivals"
        )

        arrivals = q(
            """
            SELECT
                a.name,
                f.destination_iata AS airport,
                COUNT(*) AS arrivals
            FROM flights f
            LEFT JOIN airport a
                ON a.iata_code = f.destination_iata
            WHERE f.destination_iata IS NOT NULL
            GROUP BY
                a.name,
                f.destination_iata
            ORDER BY arrivals DESC
            LIMIT 10
            """
        )

        if not arrivals.empty:

            arrivals["label"] = (
                arrivals["airport"]
                + " · "
                + arrivals["name"].fillna(
                    "Unknown"
                )
            )

            fig5 = px.bar(
                arrivals.sort_values(
                    "arrivals"
                ),
                x="arrivals",
                y="label",
                orientation="h",
                color="arrivals",
                color_continuous_scale="Purples",
            )

            fig5.update_layout(
                template="plotly_white",
                coloraxis_showscale=False,
                margin=dict(
                    l=0,
                    r=10,
                    t=5,
                    b=0,
                ),
                height=380,
                yaxis_title="",
                xaxis_title="Arrivals",
            )

            st.plotly_chart(
                fig5,
                use_container_width=True,
            )

        else:

            st.info(
                "No arrival data available."
            )

    # ========================================================
    # AIRCRAFT MODELS
    # ========================================================

    section(
        "✈️ Most-Used Aircraft Models"
    )

    model_df = q(
        """
        SELECT
            ac.model,
            COUNT(*) AS flight_count
        FROM flights f
        JOIN aircraft ac
            ON ac.registration =
               f.aircraft_registration
        WHERE ac.model IS NOT NULL
        GROUP BY ac.model
        ORDER BY flight_count DESC
        LIMIT 10
        """
    )

    if not model_df.empty:

        fig6 = px.bar(
            model_df.sort_values(
                "flight_count"
            ),
            x="flight_count",
            y="model",
            orientation="h",
            color="flight_count",
            color_continuous_scale="Greens",
        )

        fig6.update_layout(
            template="plotly_white",
            coloraxis_showscale=False,
            margin=dict(
                l=0,
                r=10,
                t=5,
                b=0,
            ),
            height=380,
            yaxis_title="",
            xaxis_title="Flights",
        )

        st.plotly_chart(
            fig6,
            use_container_width=True,
        )

    else:

        st.info(
            "No aircraft model data available."
        )

    # ========================================================
    # STATUS SUMMARY
    # ========================================================

    section(
        "📊 Flight Status Summary"
    )

    status_summary = q(
        """
        SELECT
            status,
            COUNT(*) AS total_flights
        FROM flights
        GROUP BY status
        ORDER BY total_flights DESC
        """
    )

    if not status_summary.empty:

        status_summary["status"] = status_summary["status"].apply(clean_status)
        status_summary = (
            status_summary.groupby("status", as_index=False)["total_flights"]
            .sum()
            .sort_values("total_flights", ascending=False)
        )

        st.dataframe(
            tidy(
                status_summary,
                {
                    "status": "Status",
                    "total_flights": "Flights",
                },
            ),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Air Tracker · Flight Analytics Dashboard — "
    f"data as of {datetime.now().strftime('%d %b %Y, %H:%M')} · "
    "Built with Streamlit, MySQL & AeroDataBox"
)