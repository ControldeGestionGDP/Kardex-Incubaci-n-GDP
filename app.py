import streamlit as st
import pandas as pd
from datetime import datetime, date
import sqlite3
import io

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="IncubaTrack ERP | Gestión Estratégica", page_icon="🥚", layout="wide")

# --- ESTILOS CORPORATIVOS ---
st.markdown(f"""
    <style>
    .main {{ background-color: #f8f9fa; }}
    .stButton>button {{
        background-color: #ed701b;
        color: white;
        border-radius: 5px;
        border: none;
        font-weight: bold;
        width: 100%;
        height: 3em;
    }}
    .stButton>button:hover {{ border: 2px solid #07456a; color: #07456a; }}
    h1, h2, h3 {{ color: #07456a !important; font-family: 'Segoe UI', sans-serif; }}
    
    .info-card {{
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #ed701b;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 15px;
        height: 100%;
    }}
    .info-label {{ color: #6c757d; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }}
    .info-value {{ color: #07456a; font-size: 1.1rem; font-weight: bold; }}
    
    [data-testid="stSidebar"] {{ background-color: #07456a; }}
    [data-testid="stSidebar"] * {{ color: white !important; }}
    
    .footer {{ 
        position: fixed; 
        bottom: 10px; 
        left: 0; 
        right: 0; 
        text-align: center; 
        color: #6c757d; 
        font-size: 12px; 
        font-weight: bold; 
    }}
    
    .sidebar-logo {{ font-size: 50px; text-align: center; margin-bottom: -10px; }}
    </style>
    """, unsafe_allow_html=True)

# --- SISTEMA DE BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('incubacion_ultra_v4.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS lotes (
                    id_unico TEXT PRIMARY KEY, lote_nro TEXT, procedencia TEXT, planta TEXT, 
                    gran_ja TEXT, linea_genetica TEXT, edad_repro INTEGER, 
                    fecha_postura DATE, fecha_llegada DATE, cantidad_inicial INTEGER, 
                    saldo INTEGER, obs_sanitarias TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS historial (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, id_lote TEXT, planta TEXT,
                    tipo TEXT, cantidad INTEGER, motivo TEXT, fecha TIMESTAMP)''')
    conn.commit()
    return conn

conn = init_db()
c = conn.cursor()

# --- LÓGICA DE NEGOCIO ---
def generar_id_y_procedencia(lote_txt):
    lote_txt = lote_txt.upper().strip()
    fecha_hoy = datetime.now().strftime("%d%m%y")
    if lote_txt.isdigit():
        proc = "CDG"
        id_gen = f"CDG-{lote_txt}-{fecha_hoy}"
    elif "SF" in lote_txt:
        proc = "San Fernando"
        id_gen = f"{lote_txt}-{fecha_hoy}"
    elif "SE" in lote_txt:
        proc = "Santa Elena"
        id_gen = f"{lote_txt}-{fecha_hoy}"
    else:
        proc = "Otros"
        id_gen = f"{lote_txt}-{fecha_hoy}"
    return id_gen, proc

def calcular_dias(f_postura):
    if isinstance(f_postura, str):
        f_postura = datetime.strptime(f_postura, '%Y-%m-%d').date()
    return (date.today() - f_postura).days

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Data_Incubacion')
    return output.getvalue()

# --- SIDEBAR ---
st.sidebar.markdown('<div class="sidebar-logo">🐣</div>', unsafe_allow_html=True)
st.sidebar.title("MENU ERP")
menu = ["🟢 Recepción", "🟡 Inventario Global", "📊 Seguimiento & Decisiones", "🔵 Salidas (Incubación)", "🔍 Ficha de Trazabilidad", "📜 Historial General"]
choice = st.sidebar.radio("Navegación:", menu)

# --- 🟢 1. RECEPCIÓN ---
if choice == "🟢 Recepción":
    st.header("Registro de Ingresos")
    with st.form("form_ingreso", clear_on_submit=True):
        col1, col2 = st.columns(2)
        lote_input = col1.text_input("Nro de Lote")
        planta = col2.selectbox("Planta Destino", ["P.I. Tarapoto", "P.I. Pucacaca"])
        c1, c2, c3 = st.columns(3)
        granja = c1.text_input("Granja")
        genetica = c2.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
        edad_repro = c3.number_input("Edad Repro (Semanas)", min_value=25, value=25)
        c4, c5, c6 = st.columns(3)
        cant_h = c4.number_input("Cantidad", min_value=0)
        f_postura = c5.date_input("Fecha Postura")
        f_llegada = c6.date_input("Fecha Llegada")
        obs = st.text_area("Notas Sanitarias")
        if st.form_submit_button("💾 GUARDAR REGISTRO"):
            if lote_input:
                id_u, proc = generar_id_y_procedencia(lote_input)
                try:
                    c.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", 
                              (id_u, lote_input, proc, planta, granja, genetica, edad_repro, f_postura, f_llegada, cant_h, cant_h, obs))
                    c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)", 
                              (id_u, planta, "INGRESO", cant_h, "Recepción", datetime.now()))
                    conn.commit()
                    st.success(f"✅ Lote {id_u} guardado exitosamente")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("❌ Error: Este ID ya existe en el sistema.")
            else:
                st.warning("Por favor, ingrese el número de lote.")

# --- 📊 SEGUIMIENTO & DECISIONES (ALERTAS AJUSTADAS) ---
elif choice == "📊 Seguimiento & Decisiones":
    st.header("🔬 Prioridades de Carga (Análisis de Viabilidad)")
    df = pd.read_sql_query("SELECT id_unico, fecha_postura, edad_repro, saldo, planta FROM lotes WHERE saldo > 0", conn)
    
    if not df.empty:
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        
        # Lógica de Prioridad según tus nuevos parámetros
        def evaluar_prioridad(row):
            # 1. Crítica: 10 días a más
            if row['Días Almacén'] >= 10: return "🚨 CRÍTICA (≥10 días)"
            # 2. Alta: Reproductoras viejas
            if row['edad_repro'] >= 55: return "⚠️ ALTA (Repro Vieja ≥55 sem)"
            # 3. Media: 7 a 9 días
            if 7 <= row['Días Almacén'] <= 9: return "🟡 MEDIA (7-9 días)"
            return "🟢 ÓPTIMA"

        df['Status'] = df.apply(evaluar_prioridad, axis=1)
        
        def color_status(val):
            if '🚨' in str(val): color = '#ff4b4b'
            elif '⚠️' in str(val): color = '#ffa500'
            elif '🟡' in str(val): color = '#f1c40f'
            else: color = '#2ecc71'
            return f'color: white; background-color: {color}; font-weight: bold'

        st.subheader("Plan de Carga Sugerido")
        st.dataframe(df.sort_values(by=['Días Almacén', 'edad_repro'], ascending=[False, False])
                     .style.applymap(color_status, subset=['Status']), 
                     use_container_width=True)
        
        st.info("""
        **Nuevos Criterios de Gestión:**
        * **🚨 CRÍTICA:** Huevos con 10 o más días. Riesgo de caída drástica en nacimiento.
        * **⚠️ ALTA:** Lotes de reproductoras con 55 semanas o más.
        * **🟡 MEDIA:** Huevos entre 7 y 9 días de almacenamiento.
        * **🟢 ÓPTIMA:** Huevos frescos (menos de 7 días).
        """)
    else:
        st.info("No hay inventario disponible para análisis.")

# --- 🟡 INVENTARIO GLOBAL ---
elif choice == "🟡 Inventario Global":
    st.header("📦 Stock Actual en Cámaras")
    df = pd.read_sql_query("SELECT id_unico, planta, procedencia, saldo, fecha_postura FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        st.dataframe(df, use_container_width=True)
        st.download_button("📥 Descargar Excel", to_excel(df), "Inventario_Global.xlsx")

# --- 🔵 SALIDAS (INCUBACIÓN) ---
elif choice == "🔵 Salidas (Incubación)":
    st.header("📤 Registrar Salida a Carga")
    lotes = pd.read_sql_query("SELECT id_unico, saldo FROM lotes WHERE saldo > 0", conn)
    if not lotes.empty:
        with st.form("f_salida"):
            id_s = st.selectbox("Seleccione Lote", lotes['id_unico'])
            max_val = int(lotes[lotes['id_unico']==id_s]['saldo'].values[0])
            cant = st.number_input(f"Cantidad (Disponible: {max_val})", min_value=1, max_value=max_val)
            mot = st.selectbox("Destino", ["Carga Incubadora", "Venta", "Merma/Descarte"])
            if st.form_submit_button("🚀 PROCESAR SALIDA"):
                c.execute("UPDATE lotes SET saldo = saldo - ? WHERE id_unico = ?", (cant, id_s))
                c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,'SALIDA',?,?,?)", 
                          (id_s, "PLANTA", cant, mot, datetime.now()))
                conn.commit()
                st.success("Salida procesada correctamente")
                st.rerun()

# --- 🔍 FICHA DE TRAZABILIDAD ---
elif choice == "🔍 Ficha de Trazabilidad":
    st.header("🔎 Historia del Lote")
    lotes_todos = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
    target = st.selectbox("Buscar ID:", ["Seleccionar..."] + lotes_todos['id_unico'].tolist())
    if target != "Seleccionar...":
        info = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{target}'", conn).iloc[0]
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Saldo Actual", info['saldo'])
        with c2: st.metric("Edad Repro", f"{info['edad_repro']} sem")
        with c3: st.metric("Días Almacén", calcular_dias(info['fecha_postura']))
        st.write(f"**Observaciones:** {info['obs_sanitarias']}")

# --- 📜 HISTORIAL GENERAL ---
elif choice == "📜 Historial General":
    st.header("📝 Registro General de Movimientos")
    h_df = pd.read_sql_query("SELECT * FROM historial ORDER BY fecha DESC", conn)
    st.dataframe(h_df, use_container_width=True)

# FOOTER CENTRADO
st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
