import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import io
import time
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="IncubaTrack Hub | Don Pollo", page_icon="🐣", layout="wide")

# --- DISEÑO DE SISTEMA (ESTILOS) ---
st.markdown("""
<style>
    /* Fondo y tipografía principal */
    .main { background-color: #f0f2f6; }
    
    /* Contenedores de KPIs */
    .metric-container {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border-top: 5px solid #1071B8;
        text-align: center;
    }
    
    /* Botones Estilo Hub */
    .stButton>button {
        background: linear-gradient(135deg, #1071B8 0%, #07456a 100%);
        color: white; border-radius: 8px; border: none; font-weight: 600;
        transition: all 0.3s;
    }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(16,113,184,0.3); }

    /* Sidebar Profesional */
    [data-testid="stSidebar"] { background-color: #07456a; border-right: 1px solid #e0e0e0; }
    [data-testid="stSidebar"] * { color: white !important; }
    
    .status-alert { padding: 10px; border-radius: 5px; font-weight: bold; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- NÚCLEO DE DATOS (CONEXIÓN Y CACHÉ) ---
def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

# Caché de 5 minutos para evitar bloqueos de Google API
@st.cache_data(ttl=300)
def fetch_data(sheet_name):
    try:
        client = get_gspread_client()
        SPREADSHEET_ID = "13nw5vYfEFnP3RjHXK7CC7124-MDKCe-iAwfycvTUeS0"
        ws = client.open_by_key(SPREADSHEET_ID).worksheet(sheet_name)
        data = ws.get_all_values()
        if not data: return pd.DataFrame()
        return pd.DataFrame(data[1:], columns=data[0])
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return pd.DataFrame()

# --- LÓGICA DE NEGOCIO ---
def calcular_kpis(df_lotes):
    if df_lotes.empty: return 0, 0, 0
    df_lotes['saldo'] = pd.to_numeric(df_lotes['saldo'], errors='coerce').fillna(0)
    total_huevos = df_lotes['saldo'].sum()
    cajas = total_huevos / 360
    # Alerta: Huevos con más de 10 días
    df_lotes['f_post'] = pd.to_datetime(df_lotes['fecha_postura'], errors='coerce')
    criticos = df_lotes[df_lotes['f_post'] < (datetime.now() - timedelta(days=10))]['saldo'].sum()
    return int(total_huevos), round(cajas, 1), int(criticos)

# --- COMPONENTE DE UI: DASHBOARD ---
def render_dashboard(df_lotes):
    st.subheader("🚀 Panel de Control Ejecutivo")
    total, cajas, criticos = calcular_kpis(df_lotes)
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="metric-container"><p style="color:#6c757d">STOCK TOTAL</p><h2>{total:,}</h2><p>Huevos</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-container"><p style="color:#6c757d">CAPACIDAD</p><h2>{cajas}</h2><p>Cajas (360 ud)</p></div>', unsafe_allow_html=True)
    with c3:
        color = "#d9534f" if criticos > 0 else "#5cb85c"
        st.markdown(f'<div class="metric-container" style="border-top-color:{color}"><p style="color:#6c757d">ALERTA CRÍTICA</p><h2 style="color:{color}">{criticos:,}</h2><p>> 10 días postura</p></div>', unsafe_allow_html=True)
    with c4:
        eficiencia = "94%" # Dato de ejemplo para el Hub
        st.markdown(f'<div class="metric-container"><p style="color:#6c757d">EFC. INCUBACIÓN</p><h2>{eficiencia}</h2><p>Promedio Semanal</p></div>', unsafe_allow_html=True)

# --- NAVEGACIÓN ---
st.sidebar.markdown('<h1 style="text-align:center;">🐣</h1>', unsafe_allow_html=True)
st.sidebar.title("IncubaTrack Hub")
st.sidebar.markdown("---")
menu = ["📊 Dashboard & KPIs", "🟢 Recepción Lotes", "🟡 Inventario Global", "🔵 Salidas (Cargas)", "🔍 Trazabilidad 360", "📜 Auditoría"]
choice = st.sidebar.radio("Navegación", menu)

# --- LÓGICA DE PÁGINAS ---
df_lotes = fetch_data("lotes")
df_movs = fetch_data("movimientos")

if choice == "📊 Dashboard & KPIs":
    render_dashboard(df_lotes)
    
    st.markdown("### Tendencia de Stock por Planta")
    if not df_lotes.empty:
        df_lotes['saldo'] = pd.to_numeric(df_lotes['saldo'])
        chart_data = df_lotes.groupby('planta')['saldo'].sum()
        st.bar_chart(chart_data)

elif choice == "🟢 Recepción Lotes":
    st.header("Gestión de Ingresos")
    # ... (Aquí iría tu formulario de recepción optimizado)
    st.info("Utilice esta sección para registrar la entrada de nuevos lotes de proveedores o granjas propias.")
    # Implementar aquí el código de formulario que ya tienes

elif choice == "🟡 Inventario Global":
    st.header("Stock en Cámaras")
    if not df_lotes.empty:
        df_view = df_lotes[pd.to_numeric(df_lotes['saldo']) > 0].copy()
        # Aplicar semáforo visual
        st.dataframe(df_view.style.highlight_max(axis=0, subset=['saldo']), use_container_width=True)

elif choice == "🔍 Trazabilidad 360":
    st.header("Expediente Digital de Lote")
    lote_id = st.selectbox("Seleccione ID de Lote", [""] + df_lotes['id_unico'].tolist())
    if lote_id:
        # Mostrar ficha técnica y movimientos asociados en un diseño de dos columnas
        info = df_lotes[df_lotes['id_unico'] == lote_id].iloc[0]
        col_a, col_b = st.columns(2)
        with col_a:
            st.json(info.to_dict())
        with col_b:
            movs_lote = df_movs[df_movs['id_lote'] == lote_id]
            st.table(movs_lote)

# ... (Continuar con las demás secciones siguiendo este estilo)

st.sidebar.markdown("---")
st.sidebar.caption(f"Última sincronización: {datetime.now().strftime('%H:%M:%S')}")
if st.sidebar.button("🔄 Forzar Refresco"):
    st.cache_data.clear()
    st.rerun()

st.markdown('<div style="text-align:center; color:gray; margin-top:50px;">Portal de Inteligencia Don Pollo © 2026</div>', unsafe_allow_html=True)
