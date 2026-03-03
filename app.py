import streamlit as st
import pandas as pd
from datetime import datetime, date
import io
import time
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="IncubaTrack ERP | Gestión Estratégica", page_icon="🥚", layout="wide")

# --- ESTILOS CORPORATIVOS ---
st.markdown("""
<style>
.main { background-color: #f8f9fa; }
.stButton>button {
    background-color: #ed701b;
    color: white;
    border-radius: 5px;
    border: none;
    font-weight: bold;
    width: 100%;
    height: 3em;
}
.stButton>button:hover { border: 2px solid #07456a; color: #07456a; }
h1, h2, h3 { color: #07456a !important; font-family: 'Segoe UI', sans-serif; }

.info-card {
    background-color: white;
    padding: 15px;
    border-radius: 10px;
    border-left: 5px solid #ed701b;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    margin-bottom: 15px;
}

.info-label { color: #6c757d; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
.info-value { color: #07456a; font-size: 1.1rem; font-weight: bold; }

[data-testid="stSidebar"] { background-color: #07456a; }
[data-testid="stSidebar"] * { color: white !important; }

.footer {
    position: fixed;
    bottom: 10px;
    left: 0;
    right: 0;
    text-align: center;
    color: #6c757d;
    font-size: 12px;
    font-weight: bold;
}
.sidebar-logo { font-size: 50px; text-align: center; margin-bottom: -10px; }

/* Animación de pollitos */
@keyframes falling {
    0% { transform: translateY(-10vh) translateX(0) rotate(0deg); opacity: 1; }
    100% { transform: translateY(100vh) translateX(20px) rotate(360deg); opacity: 0; }
}
.pollito-anim {
    position: fixed;
    top: -5vh;
    font-size: 2.5rem;
    z-index: 999999;
    pointer-events: none;
    animation: falling 2s linear forwards;
}
</style>
""", unsafe_allow_html=True)

# --- FUNCIÓN PARA LLUVIA DE POLLITOS ---
def lluvia_de_pollitos():
    container = st.empty()
    pollitos_html = ""
    for i in range(30):
        pos_x = i * 3.3
        delay = (i % 5) * 0.2
        pollitos_html += f'<div class="pollito-anim" style="left:{pos_x}%; animation-delay:{delay}s;">🐣</div>'
    container.markdown(pollitos_html, unsafe_allow_html=True)
    time.sleep(2.5)
    container.empty()

# --- CONEXIÓN GOOGLE SHEETS ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
client = gspread.authorize(creds)
SPREADSHEET_ID = "13nw5vYfEFnP3RjHXK7CC7124-MDKCe-iAwfycvTUeS0"
lotes_ws = client.open_by_key(SPREADSHEET_ID).worksheet("lotes")
movimientos_ws = client.open_by_key(SPREADSHEET_ID).worksheet("movimientos")

# --- FUNCIONES BASE ---
def cargar_lotes():
    return pd.DataFrame(lotes_ws.get_all_records())

def cargar_movimientos():
    return pd.DataFrame(movimientos_ws.get_all_records())

def insertar_lote(row):
    lotes_ws.append_row(row)

def insertar_movimiento(row):
    movimientos_ws.append_row(row)

def actualizar_saldo(id_unico, nuevo_saldo):
    df = cargar_lotes()
    fila = df[df["id_unico"] == id_unico].index
    if len(fila) > 0:
        row_number = fila[0] + 2
        col_index = df.columns.get_loc("saldo") + 1
        lotes_ws.update_cell(row_number, col_index, nuevo_saldo)

def generar_id_y_procedencia(lote_txt):
    lote_txt = lote_txt.upper().strip()
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    if lote_txt.isdigit():
        return f"CDG-{lote_txt}-{timestamp}", "CDG"
    elif "SF" in lote_txt:
        return f"{lote_txt}-{timestamp}", "San Fernando"
    elif "SE" in lote_txt:
        return f"{lote_txt}-{timestamp}", "Santa Elena"
    return f"{lote_txt}-{timestamp}", "Otros"

def calcular_dias(f_postura):
    if isinstance(f_postura, str):
        f_postura = datetime.strptime(f_postura, "%Y-%m-%d").date()
    return (date.today() - f_postura).days

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- SIDEBAR ---
st.sidebar.markdown('<div class="sidebar-logo">🐣</div>', unsafe_allow_html=True)
st.sidebar.title("MENU ERP")
menu = ["🟢 Recepción", "🟡 Inventario Global", "🔵 Salidas", "📜 Historial"]
choice = st.sidebar.radio("Navegación:", menu)

# --- 🟢 RECEPCIÓN ---
if choice == "🟢 Recepción":
    st.header("Registro de Ingresos")
    with st.form("form_ingreso", clear_on_submit=True):
        col1, col2 = st.columns(2)
        lote_input = col1.text_input("Nro de Lote")
        planta = col2.selectbox("Planta Destino", ["P.I. Tarapoto", "P.I. Pucacaca"])
        granja = st.text_input("Granja")
        genetica = st.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
        edad_repro = st.number_input("Edad Repro", min_value=0)
        cant_h = st.number_input("Cantidad", min_value=0)
        f_postura = st.date_input("Fecha Postura")
        f_llegada = st.date_input("Fecha Llegada")
        obs = st.text_area("Notas Sanitarias")

        if st.form_submit_button("💾 GUARDAR REGISTRO"):
            if not lote_input:
                st.error("El número de lote es obligatorio")
            else:
                id_u, proc = generar_id_y_procedencia(lote_input)
                insertar_lote([id_u, lote_input, proc, planta, granja, genetica, edad_repro, str(f_postura), str(f_llegada), cant_h, cant_h, obs])
                insertar_movimiento(["", id_u, planta, "INGRESO", cant_h, "Recepción", str(datetime.now())])
                st.success(f"Lote {id_u} registrado correctamente")
                lluvia_de_pollitos()
                st.rerun()

# --- 🟡 INVENTARIO ---
elif choice == "🟡 Inventario Global":
    st.header("Consolidado de Stock")
    df = cargar_lotes()
    if not df.empty:
        df = df[df["saldo"] > 0]
        df["Días Almacén"] = df["fecha_postura"].apply(calcular_dias)
        st.dataframe(df, use_container_width=True)
        st.download_button("📥 DESCARGAR EXCEL", to_excel(df), "Inventario.xlsx")

# --- 🔵 SALIDAS ---
elif choice == "🔵 Salidas":
    st.header("Orden de Salida")
    df = cargar_lotes()
    df = df[df["saldo"] > 0]
    if not df.empty:
        with st.form("form_salida", clear_on_submit=True):
            id_s = st.selectbox("Seleccione Lote", df["id_unico"])
            cant = st.number_input("Cantidad", min_value=1)
            mot = st.selectbox("Motivo", ["Carga Incubadora", "Venta", "Merma"])
            if st.form_submit_button("🚀 PROCESAR SALIDA"):
                lote_info = df[df["id_unico"] == id_s].iloc[0]
                if cant <= lote_info["saldo"]:
                    nuevo_saldo = lote_info["saldo"] - cant
                    actualizar_saldo(id_s, nuevo_saldo)
                    insertar_movimiento(["", id_s, lote_info["planta"], "SALIDA", cant, mot, str(datetime.now())])
                    st.success(f"Salida registrada: {cant} huevos de {id_s}")
                    lluvia_de_pollitos()
                    st.rerun()
                else:
                    st.error("Saldo insuficiente")

# --- 📜 HISTORIAL ---
elif choice == "📜 Historial":
    st.header("Auditoría de Movimientos")
    h_df = cargar_movimientos()
    if not h_df.empty:
        st.dataframe(h_df, use_container_width=True)
        st.download_button("📥 DESCARGAR HISTORIAL", to_excel(h_df), "Historial.xlsx")

st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
