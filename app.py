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
                    granja TEXT, linea_genetica TEXT, edad_repro INTEGER, 
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
        procedencia = "CDG"
        id_gen = f"CDG-{lote_txt}-{fecha_hoy}"
    elif "SF" in lote_txt:
        procedencia = "San Fernando"
        id_gen = f"{lote_txt}-{fecha_hoy}"
    elif "SE" in lote_txt:
        procedencia = "Santa Elena"
        id_gen = f"{lote_txt}-{fecha_hoy}"
    else:
        procedencia = "Otros"
        id_gen = f"{lote_txt}-{fecha_hoy}"
    return id_gen, procedencia

def calcular_dias(f_postura):
    if isinstance(f_postura, str):
        f_postura = datetime.strptime(f_postura, '%Y-%m-%d').date()
    return (date.today() - f_postura).days

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte_Incubacion')
    return output.getvalue()

# --- SIDEBAR ---
st.sidebar.markdown('<div class="sidebar-logo">🐣</div>', unsafe_allow_html=True)
st.sidebar.title("MENU ERP")
menu = ["🟢 Recepción", "🟡 Inventario Global", "📊 Seguimiento & Decisiones", "🔵 Salidas (Incubación)", "🔍 Ficha de Trazabilidad", "📜 Historial General"]
choice = st.sidebar.radio("Navegación:", menu)

# --- 🟢 1. RECEPCIÓN ---
if choice == "🟢 Recepción":
    t1, t2 = st.tabs(["📥 Nuevo Ingreso", "✏️ Editar/Corregir"])
    with t1:
        st.header("Registro de Ingresos")
        with st.form("form_ingreso", clear_on_submit=True):
            col1, col2 = st.columns(2)
            lote_input = col1.text_input("Nro de Lote")
            planta = col2.selectbox("Planta Destino", ["P.I. Tarapoto", "P.I. Pucacaca"])
            c1, c2, c3 = st.columns(3); granja = c1.text_input("Granja"); genetica = c2.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"]); edad_repro = c3.number_input("Edad Repro", min_value=0, value=0)
            c4, c5, c6 = st.columns(3); cant_h = c4.number_input("Cantidad", min_value=0); f_postura = c5.date_input("Fecha Postura"); f_llegada = c6.date_input("Fecha Llegada")
            obs = st.text_area("Notas Sanitarias")
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                id_u, proc = generar_id_y_procedencia(lote_input)
                try:
                    c.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (id_u, lote_input, proc, planta, granja, genetica, (edad_repro if edad_repro > 0 else None), f_postura, f_llegada, cant_h, cant_h, obs))
                    c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)", (id_u, planta, "INGRESO", cant_h, "Recepción", datetime.now()))
                    conn.commit(); st.success(f"✅ Lote {id_u} guardado"); st.balloons(); st.rerun()
                except: st.error("❌ Error de Guardado.")

# --- 🟡 INVENTARIO GLOBAL ---
elif choice == "🟡 Inventario Global":
    st.header("📦 Consolidado de Stock")
    df = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        st.dataframe(df[['id_unico', 'planta', 'procedencia', 'saldo', 'Días Almacén']], use_container_width=True)

# --- 📊 SEGUIMIENTO & DECISIONES (ALERTAS DE PRIORIDAD) ---
elif choice == "📊 Seguimiento & Decisiones":
    st.header("🔬 Prioridades de Carga (Análisis Biológico)")
    df = pd.read_sql_query("SELECT id_unico, fecha_postura, edad_repro, saldo, planta FROM lotes WHERE saldo > 0", conn)
    
    if not df.empty:
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        
        # Lógica de Prioridad Avanzada
        def evaluar_prioridad(row):
            # Prioridad por Almacenamiento
            if row['Días Almacén'] >= 7: return "🚨 CRÍTICA (Antigüedad)"
            # Prioridad por Edad de Reproductora (Ejemplo: menores de 25 o mayores de 60 sem)
            if row['edad_repro'] and (row['edad_repro'] < 25 or row['edad_repro'] > 55): 
                return "⚠️ ALTA (Edad Repro)"
            if row['Días Almacén'] >= 4: return "🟡 MEDIA"
            return "🟢 NORMAL"

        df['Prioridad'] = df.apply(evaluar_prioridad, axis=1)
        
        # Coloreo de tabla
        def color_prioridad(val):
            if '🚨' in str(val): color = '#ff4b4b'
            elif '⚠️' in str(val): color = '#ffa500'
            elif '🟡' in str(val): color = '#f1c40f'
            else: color = '#2ecc71'
            return f'color: white; background-color: {color}; font-weight: bold'

        st.subheader("Planificación de Carga Sugerida")
        st.dataframe(df.sort_values(by=['Días Almacén', 'edad_repro'], ascending=[False, False])
                     .style.applymap(color_prioridad, subset=['Prioridad']), 
                     use_container_width=True)
        
        st.info("""
        **Criterios de Prioridad:**
        * **CRÍTICA:** Huevos con 7 o más días de almacenamiento (pérdida de viabilidad).
        * **ALTA:** Reproductoras jóvenes (<25 sem) o viejas (>55 sem) requieren rotación rápida.
        * **MEDIA:** Huevos entre 4 y 6 días.
        """)
    else:
        st.info("No hay lotes con saldo para analizar.")

# --- 🔵 SALIDAS ---
elif choice == "🔵 Salidas (Incubación)":
    st.header("📤 Orden de Salida")
    lotes = pd.read_sql_query("SELECT id_unico, saldo FROM lotes WHERE saldo > 0", conn)
    if not lotes.empty:
        with st.form("f_sal"):
            id_s = st.selectbox("Lote", lotes['id_unico'])
            cant = st.number_input("Cantidad", min_value=1)
            mot = st.selectbox("Destino", ["Carga Incubadora", "Venta", "Merma"])
            if st.form_submit_button("🚀 PROCESAR"):
                c.execute("UPDATE lotes SET saldo = saldo - ? WHERE id_unico = ?", (cant, id_s))
                c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)", (id_s, "PLANTA", "SALIDA", cant, mot, datetime.now()))
                conn.commit(); st.success("Salida registrada"); st.rerun()

# --- 🔍 5. FICHA DE TRAZABILIDAD ---
elif choice == "🔍 Ficha de Trazabilidad":
    st.header("🔎 Expediente de Lote")
    lotes_todos = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
    target = st.selectbox("Buscar Lote:", ["Seleccionar..."] + lotes_todos['id_unico'].tolist())
    
    if target != "Seleccionar...":
        info = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{target}'", conn).iloc[0]
        st.subheader(f"Resumen del Lote: {target}")
        col1, col2, col3 = st.columns(3)
        with col1: st.markdown(f'<div class="info-card"><div class="info-label">Saldo</div><div class="info-value">{info["saldo"]}</div></div>', unsafe_allow_html=True)
        with col2: st.markdown(f'<div class="info-card"><div class="info-label">Edad Repro</div><div class="info-value">{info["edad_repro"]} Sem.</div></div>', unsafe_allow_html=True)
        with col3: st.markdown(f'<div class="info-card"><div class="info-label">Procedencia</div><div class="info-value">{info["procedencia"]}</div></div>', unsafe_allow_html=True)

# --- 📜 HISTORIAL GENERAL ---
elif choice == "📜 Historial General":
    st.header("📝 Auditoría de Movimientos")
    h_df = pd.read_sql_query("SELECT * FROM historial ORDER BY fecha DESC", conn)
    st.dataframe(h_df, use_container_width=True)

st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
