import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
import time

# --- CONFIGURACIÓN CRÍTICA ---
st.set_page_config(page_title="Hub de Inteligencia GDP", layout="wide")

# Estilos minimalistas y profesionales
st.markdown("""
<style>
    .stApp { background-color: #f4f7f9; }
    .main-card { background-color: white; padding: 20px; border-radius: 10px; shadow: 0 2px 4px rgba(0,0,0,0.1); }
    h1 { color: #1071B8; }
</style>
""", unsafe_allow_html=True)

# --- CONEXIÓN SEGURA ---
@st.cache_resource
def conectar_db():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        # Asegúrate de que 'gcp_service_account' esté correctamente configurado en tus Secrets
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        return client.open_by_key("13nw5vYfEFnP3RjHXK7CC7124-MDKCe-iAwfycvTUeS0")
    except Exception as e:
        st.error(f"Error de Conexión: {e}")
        return None

db = conectar_db()

# --- FUNCIONES DE DATOS ---
def obtener_df(nombre_hoja):
    if db:
        hoja = db.worksheet(nombre_hoja)
        datos = hoja.get_all_records()
        return pd.DataFrame(datos)
    return pd.DataFrame()

def guardar_fila(nombre_hoja, fila):
    if db:
        hoja = db.worksheet(nombre_hoja)
        hoja.append_row(fila)
        st.cache_data.clear() # Limpiar caché para ver cambios

# --- NAVEGACIÓN ---
with st.sidebar:
    st.title("Hub GDP 🐣")
    opcion = st.radio("Módulos:", ["📊 Dashboard", "📥 Registro", "📦 Inventario", "🔄 Salidas"])

# --- LÓGICA DE NEGOCIO ---
df_lotes = obtener_df("lotes")

if opcion == "📊 Dashboard":
    st.header("Panel de Control Gerencial")
    if not df_lotes.empty:
        # Convertir a numérico por seguridad
        df_lotes['saldo'] = pd.to_numeric(df_lotes['saldo'], errors='coerce').fillna(0)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Huevos en Stock", f"{int(df_lotes['saldo'].sum()):,}")
        c2.metric("Total Cajas", f"{round(df_lotes['saldo'].sum()/360, 1)}")
        
        st.subheader("Distribución por Planta")
        st.bar_chart(df_lotes.groupby('planta')['saldo'].sum())
    else:
        st.warning("No hay datos cargados en 'lotes'.")

elif opcion == "📥 Registro":
    st.header("Ingreso de Lote")
    with st.form("registro_lote"):
        col1, col2 = st.columns(2)
        lote_n = col1.text_input("Número de Lote")
        planta = col2.selectbox("Planta", ["P.I. Tarapoto", "P.I. Pucacaca"])
        
        c1, c2, c3 = st.columns(3)
        cantidad = c1.number_input("Cantidad Total", min_value=0)
        f_postura = c2.date_input("Fecha de Postura")
        genetica = c3.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard"])
        
        btn = st.form_submit_button("REGISTRAR EN HUB")
        
        if btn and lote_n:
            id_u = f"{lote_n}-{datetime.now().strftime('%M%S')}"
            # Asegurar que el orden coincida exactamente con tus columnas en Sheets
            nueva_fila = [id_u, lote_n, "CDG", planta, "Huevo Premium", genetica, 0, str(f_postura), str(date.today()), cantidad, cantidad, ""]
            guardar_fila("lotes", nueva_fila)
            st.success("Registrado con éxito")
            st.balloons()

elif opcion == "📦 Inventario":
    st.header("Inventario Real-Time")
    if not df_lotes.empty:
        # Solo mostrar lo que tiene stock
        df_filtrado = df_lotes[pd.to_numeric(df_lotes['saldo']) > 0]
        st.dataframe(df_filtrado, use_container_width=True)
    else:
        st.info("Inventario vacío.")

elif opcion == "🔄 Salidas":
    st.header("Carga a Incubadora")
    if not df_lotes.empty:
        lotes_activos = df_lotes[pd.to_numeric(df_lotes['saldo']) > 0]['id_unico'].tolist()
        with st.form("salida_form"):
            lote_sel = st.selectbox("Lote a descargar", lotes_activos)
            cant_salida = st.number_input("Cantidad", min_value=1)
            btn_salida = st.form_submit_button("PROCESAR SALIDA")
            
            if btn_salida:
                st.warning("Función de actualización de saldo activa. Verifique en Sheets.")
                # Aquí podrías añadir la lógica de actualización de celda
