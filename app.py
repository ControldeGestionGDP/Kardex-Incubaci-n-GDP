import streamlit as st
import pandas as pd
from datetime import datetime, date
import sqlite3
import io

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="IncubaTrack ERP | Gestión Estratégica", page_icon="🥚", layout="wide")

# --- ESTILOS CORPORATIVOS (#ed701b y #07456a) ---
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
    }}
    .stButton>button:hover {{ border: 2px solid #07456a; color: #07456a; }}
    h1, h2, h3 {{ color: #07456a !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
    .stMetric {{ background-color: white; padding: 15px; border-radius: 10px; border-left: 5px solid #ed701b; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }}
    [data-testid="stSidebar"] {{ background-color: #07456a; }}
    [data-testid="stSidebar"] * {{ color: white !important; }}
    .footer {{ position: fixed; bottom: 10px; right: 10px; color: #6c757d; font-size: 12px; font-weight: bold; }}
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
                    saldo INTEGER, transportista TEXT, obs_sanitarias TEXT)''')
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
        df.to_excel(writer, index=False, sheet_name='Kardex_Incubacion')
    return output.getvalue()

# --- SIDEBAR CORPORATIVO ---
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/3069/3069172.png", width=80)
st.sidebar.title("MENU ERP")
menu = ["🟢 Recepción", "🟡 Inventario Global", "📊 Seguimiento & Decisiones", "🔵 Salidas (Incubación)", "🔍 Ficha de Trazabilidad", "📜 Historial General"]
choice = st.sidebar.radio("Navegación:", menu)

st.sidebar.divider()
st.sidebar.info("💡 **Estado del Sistema:** Conectado a Servidor Local")

# ---------------------------------------------------------
# 🟢 1. RECEPCIÓN
# ---------------------------------------------------------
if choice == "🟢 Recepción":
    tab1, tab2 = st.tabs(["📥 Registro de Nuevo Lote", "✏️ Modificar/Corregir Datos"])
    
    with tab1:
        st.header("Registro de Ingresos")
        with st.form("form_ingreso", clear_on_submit=True):
            col1, col2 = st.columns(2)
            lote_input = col1.text_input("Nro de Lote", help="Números=CDG | SF=San Fernando | SE=Santa Elena")
            planta = col2.selectbox("Planta Destino", ["P.I. Tarapoto", "P.I. Pucacaca"])
            
            c1, c2, c3 = st.columns(3)
            granja = c1.text_input("Granja")
            genetica = c2.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
            edad_repro = c3.number_input("Edad Repro (Semanas)", min_value=0, value=0)
            
            c4, c5, c6 = st.columns(3)
            cant_h = c4.number_input("Cantidad de Huevos", min_value=0)
            f_postura = c5.date_input("Fecha de Postura")
            f_llegada = c6.date_input("Fecha de Llegada")
            
            transp = st.text_input("Transportista / Chofer")
            obs = st.text_area("Notas Sanitarias")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                id_u, proc = generar_id_y_procedencia(lote_input)
                val_edad = edad_repro if edad_repro > 0 else None
                try:
                    c.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (id_u, lote_input, proc, planta, granja, genetica, val_edad, f_postura, f_llegada, cant_h, cant_h, transp, obs))
                    c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)",
                              (id_u, planta, "INGRESO", cant_h, "Recepción Inicial", datetime.now()))
                    conn.commit()
                    st.success(f"📦 ¡Lote {id_u} guardado satisfactoriamente!")
                    st.balloons()
                except: st.error("❌ Error: Este lote ya fue registrado hoy.")

    with tab2:
        st.header("Editor de Lotes Registrados")
        lotes_lista = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
        id_edit = st.selectbox("Seleccione ID para editar:", ["Seleccionar..."] + lotes_lista['id_unico'].tolist())
        
        if id_edit != "Seleccionar...":
            datos = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{id_edit}'", conn).iloc[0]
            f_p_val = datetime.strptime(datos['fecha_postura'], '%Y-%m-%d').date() if isinstance(datos['fecha_postura'], str) else datos['fecha_postura']
            f_l_val = datetime.strptime(datos['fecha_llegada'], '%Y-%m-%d').date() if isinstance(datos['fecha_llegada'], str) else datos['fecha_llegada']

            with st.form("form_edicion"):
                col_e1, col_e2 = st.columns(2)
                e_granja = col_e1.text_input("Corregir Granja", value=datos['granja'])
                e_planta = col_e2.selectbox("Cambiar Planta", ["P.I. Tarapoto", "P.I. Pucacaca"], index=0 if datos['planta']=="P.I. Tarapoto" else 1)
                
                col_f1, col_f2 = st.columns(2)
                e_f_postura = col_f1.date_input("Fecha Postura", value=f_p_val)
                e_f_llegada = col_f2.date_input("Fecha Llegada", value=f_l_val)

                ce1, ce2, ce3 = st.columns(3)
                e_gen = ce1.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
                e_edad = ce2.number_input("Edad Repro", value=int(datos['edad_repro']) if datos['edad_repro'] else 0)
                e_saldo = ce3.number_input("Ajustar Saldo Fisico", value=int(datos['saldo']))
                
                e_obs = st.text_area("Observaciones", value=datos['obs_sanitarias'])
                
                if st.form_submit_button("🔄 ACTUALIZAR CAMBIOS"):
                    c.execute('''UPDATE lotes SET granja=?, planta=?, fecha_postura=?, fecha_llegada=?, 
                                 linea_genetica=?, edad_repro=?, saldo=?, obs_sanitarias=? 
                                 WHERE id_unico=?''', 
                              (e_granja, e_planta, e_f_postura, e_f_llegada, e_gen, 
                               e_edad if e_edad > 0 else None, e_saldo, e_obs, id_edit))
                    conn.commit()
                    st.toast("Cambios aplicados con éxito", icon="✅")
                    st.success("✅ Información de lote actualizada correctamente.")

# ---------------------------------------------------------
# 🟡 2. INVENTARIO GLOBAL
# ---------------------------------------------------------
elif choice == "🟡 Inventario Global":
    st.header("📦 Consolidado de Stock")
    df = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        col_f1, col_f2 = st.columns(2)
        f_proc = col_f1.multiselect("Filtrar Procedencia:", df['procedencia'].unique(), default=df['procedencia'].unique())
        f_planta = col_f2.multiselect("Filtrar Planta:", df['planta'].unique(), default=df['planta'].unique())
        df = df[(df['procedencia'].isin(f_proc)) & (df['planta'].isin(f_planta))]
        
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        df['Cajas'] = (df['saldo'] / 360).round(2)
        
        st.dataframe(df[['id_unico', 'planta', 'procedencia', 'lote_nro', 'saldo', 'Cajas', 'Días Almacén']], use_container_width=True)
        st.download_button("📥 DESCARGAR REPORTE EXCEL", to_excel(df), "Stock_IncubaTrack.xlsx")
    else: st.info("Cámara Fría vacía.")

# ---------------------------------------------------------
# 📊 3. SEGUIMIENTO
# ---------------------------------------------------------
elif choice == "📊 Seguimiento & Decisiones":
    st.header("🔬 Análisis de Rotación")
    df_d = pd.read_sql_query("SELECT id_unico, planta, edad_repro, fecha_postura, saldo FROM lotes WHERE saldo > 0", conn)
    if not df_d.empty:
        df_d['Días Almacén'] = df_d['fecha_postura'].apply(calcular_dias)
        def semaforo(row):
            if row['Días Almacén'] > 10: return "🔴 CRÍTICO"
            if pd.notnull(row['edad_repro']) and row['edad_repro'] > 60: return "🟠 REPRO VIEJA"
            return "🟢 ÓPTIMO"
        df_d['Status'] = df_d.apply(semaforo, axis=1)
        st.table(df_d[['id_unico', 'planta', 'Días Almacén', 'Status']].sort_values(by="Días Almacén", ascending=False))

# ---------------------------------------------------------
# 🔵 4. SALIDAS
# ---------------------------------------------------------
elif choice == "🔵 Salidas (Incubación)":
    st.header("📤 Orden de Salida")
    lotes_activos = pd.read_sql_query("SELECT id_unico, saldo, planta FROM lotes WHERE saldo > 0", conn)
    if not lotes_activos.empty:
        with st.form("form_salida"):
            c_s1, c_s2 = st.columns(2)
            id_salida = c_s1.selectbox("Lote a descargar", lotes_activos['id_unico'])
            saldo_max = lotes_activos[lotes_activos['id_unico'] == id_salida]['saldo'].values[0]
            cant_salida = c_s2.number_input(f"Cantidad (Disponible: {saldo_max})", min_value=1, max_value=int(saldo_max))
            motivo = st.selectbox("Destino de Salida", ["Carga Incubadora", "Venta", "Merma", "Ajuste de Inventario"])
            
            if st.form_submit_button("🚀 CONFIRMAR SALIDA"):
                c.execute("UPDATE lotes SET saldo = saldo - ? WHERE id_unico = ?", (cant_salida, id_salida))
                c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)",
                          (id_salida, "PLANTA", "SALIDA", cant_salida, motivo, datetime.now()))
                conn.commit()
                st.success(f"✅ Salida de {cant_salida} unidades procesada con éxito.")
                st.toast("Inventario actualizado", icon="📉")
                st.rerun()

# ---------------------------------------------------------
# 🔍 5. TRAZABILIDAD
# ---------------------------------------------------------
elif choice == "🔍 Ficha de Trazabilidad":
    st.header("🔎 Expediente de Lote")
    lotes_todos = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
    target = st.selectbox("Buscar Lote:", ["Seleccionar..."] + lotes_todos['id_unico'].tolist())
    
    if target != "Seleccionar...":
        info = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{target}'", conn).iloc[0]
        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("SALDO ACTUAL", f"{info['saldo']} und")
        m2.metric("CAJAS EQUIV.", f"{round(info['saldo']/360, 1)}")
        m3.metric("ANTIGÜEDAD", f"{calcular_dias(info['fecha_postura'])} días")
        m4.metric("REPRO", f"{info['edad_repro'] if info['edad_repro'] else 'S/D'} sem")
        
        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown(f"**Granja:** {info['granja']} | **Genética:** {info['linea_genetica']}")
            st.markdown(f"**Procedencia:** {info['procedencia']} | **Planta:** {info['planta']}")
        with c_b:
            st.markdown(f"**Transportista:** {info['transportista']}")
            st.info(f"**Obs:** {info['obs_sanitarias']}")

# ---------------------------------------------------------
# 📜 6. HISTORIAL
# ---------------------------------------------------------
elif choice == "📜 Historial General":
    st.header("📝 Auditoría de Movimientos")
    h_df = pd.read_sql_query("SELECT * FROM historial ORDER BY fecha DESC", conn)
    st.dataframe(h_df, use_container_width=True)

# --- FOOTER CORPORATIVO ---
st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
