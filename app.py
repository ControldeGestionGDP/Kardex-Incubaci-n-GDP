import streamlit as st
import pandas as pd
from datetime import datetime, date
import sqlite3
import io
import time

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
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    if lote_txt.isdigit():
        procedencia = "CDG"
        id_gen = f"CDG-{lote_txt}-{timestamp}"
    elif "SF" in lote_txt:
        procedencia = "San Fernando"
        id_gen = f"{lote_txt}-{timestamp}"
    elif "SE" in lote_txt:
        procedencia = "Santa Elena"
        id_gen = f"{lote_txt}-{timestamp}"
    else:
        procedencia = "Otros"
        id_gen = f"{lote_txt}-{timestamp}"
    return id_gen, procedencia

def calcular_dias(f_postura):
    if isinstance(f_postura, str):
        f_postura = datetime.strptime(f_postura, '%Y-%m-%d').date()
    return (date.today() - f_postura).days

def clasificar_repro(edad):
    if not edad or edad == 0: return "S/D"
    if edad < 30: return "Joven (<30)"
    if 30 <= edad <= 39: return "Óptima (30-39)"
    if 40 <= edad <= 49: return "Madura (40-49)"
    return "Vieja (≥50)"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte')
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
                if not lote_input:
                    st.error("❌ El número de lote es obligatorio.")
                else:
                    id_u, proc = generar_id_y_procedencia(lote_input)
                    try:
                        sql_lotes = """INSERT INTO lotes 
                                     (id_unico, lote_nro, procedencia, planta, granja, linea_genetica, 
                                      edad_repro, fecha_postura, fecha_llegada, cantidad_inicial, saldo, obs_sanitarias) 
                                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""
                        c.execute(sql_lotes, (id_u, lote_input, proc, planta, granja, genetica, 
                                            (edad_repro if edad_repro > 0 else None), f_postura, f_llegada, 
                                            cant_h, cant_h, obs))
                        c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)", 
                                 (id_u, planta, "INGRESO", cant_h, "Recepción", datetime.now()))
                        conn.commit()
                        st.toast(f"Lote {id_u} registrado", icon="📥")
                        st.success(f"✅ Lote {id_u} guardado correctamente."); st.balloons(); time.sleep(1); st.rerun()
                    except Exception as e: 
                        st.error(f"❌ Error al guardar: {e}")

    with t2:
        st.header("Editor de Lotes")
        lista = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
        id_edit = st.selectbox("Seleccione ID:", ["Seleccionar..."] + lista['id_unico'].tolist())
        if id_edit != "Seleccionar...":
            datos = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{id_edit}'", conn).iloc[0]
            with st.form("f_edit"):
                col_e1, col_e2 = st.columns(2); e_granja = col_e1.text_input("Granja", value=datos['granja']); e_planta = col_e2.selectbox("Planta", ["P.I. Tarapoto", "P.I. Pucacaca"], index=0 if datos['planta']=="P.I. Tarapoto" else 1)
                col_f1, col_f2 = st.columns(2); e_f_postura = col_f1.date_input("Fecha Postura", value=pd.to_datetime(datos['fecha_postura']).date()); e_f_llegada = col_f2.date_input("Fecha Llegada", value=pd.to_datetime(datos['fecha_llegada']).date())
                ce1, ce2, ce3 = st.columns(3); e_gen = ce1.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"]); e_edad = ce2.number_input("Edad Repro", value=int(datos['edad_repro']) if datos['edad_repro'] else 0); e_saldo = ce3.number_input("Saldo", value=int(datos['saldo']))
                e_obs = st.text_area("Observaciones", value=datos['obs_sanitarias'])
                if st.form_submit_button("🔄 ACTUALIZAR DATOS"):
                    c.execute("UPDATE lotes SET granja=?, planta=?, fecha_postura=?, fecha_llegada=?, linea_genetica=?, edad_repro=?, saldo=?, obs_sanitarias=? WHERE id_unico=?", (e_granja, e_planta, e_f_postura, e_f_llegada, e_gen, e_edad, e_saldo, e_obs, id_edit))
                    conn.commit()
                    st.toast("Datos actualizados con éxito", icon="🔄")
                    st.info(f"Lote {id_edit} ha sido modificado."); time.sleep(1.5); st.rerun()

# --- 🟡 INVENTARIO GLOBAL (CON BUSCADORES) ---
elif choice == "🟡 Inventario Global":
    st.header("📦 Consolidado de Stock")
    df = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        # Fila de Buscadores
        b1, b2, b3 = st.columns(3)
        search_lote = b1.text_input("🔍 Buscar por Nro Lote:")
        filter_planta = b2.multiselect("Filtrar Planta:", df['planta'].unique(), default=df['planta'].unique())
        filter_proc = b3.multiselect("Filtrar Procedencia:", df['procedencia'].unique(), default=df['procedencia'].unique())
        
        # Aplicar filtros al DataFrame
        if search_lote:
            df = df[df['lote_nro'].str.contains(search_lote, case=False)]
        df = df[df['planta'].isin(filter_planta)]
        df = df[df['procedencia'].isin(filter_proc)]

        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        cols = ['id_unico', 'saldo', 'Días Almacén', 'planta', 'procedencia', 'granja', 'linea_genetica', 'edad_repro', 'fecha_postura', 'fecha_llegada', 'obs_sanitarias']
        st.dataframe(df[cols], use_container_width=True)
        if st.download_button("📥 DESCARGAR EXCEL FILTRADO", to_excel(df), "Inventario.xlsx"):
            st.toast("Descarga iniciada", icon="📊")

# --- 📊 SEGUIMIENTO & DECISIONES (CON BUSCADORES) ---
elif choice == "📊 Seguimiento & Decisiones":
    st.header("🔬 Prioridades de Carga")
    df = pd.read_sql_query("SELECT id_unico, planta, granja, linea_genetica, edad_repro, fecha_postura, saldo FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        # Fila de Buscadores
        s1, s2 = st.columns(2)
        f_planta = s1.multiselect("Planta:", df['planta'].unique(), default=df['planta'].unique())
        f_gen = s2.multiselect("Genética:", df['linea_genetica'].unique(), default=df['linea_genetica'].unique())
        
        df = df[df['planta'].isin(f_planta)]
        df = df[df['linea_genetica'].isin(f_gen)]

        df['Días'] = df['fecha_postura'].apply(calcular_dias)
        df['Clasif. Repro'] = df['edad_repro'].apply(clasificar_repro)
        df = df.sort_values(by="Días", ascending=False)
        def color_semaforo(row):
            if row['Días'] > 10: return ['background-color: #ffcccc'] * len(row)
            elif 7 <= row['Días'] <= 9: return ['background-color: #fff4cc'] * len(row)
            else: return ['background-color: #d4edda'] * len(row)
        st.dataframe(df.style.apply(color_semaforo, axis=1), use_container_width=True)

# --- 🔵 SALIDAS ---
elif choice == "🔵 Salidas (Incubación)":
    st.header("📤 Orden de Salida")
    lotes_disponibles = pd.read_sql_query("SELECT id_unico, saldo, planta FROM lotes WHERE saldo > 0", conn)
    if not lotes_disponibles.empty:
        with st.form("form_salida", clear_on_submit=True):
            id_s = st.selectbox("Seleccione Lote", lotes_disponibles['id_unico'])
            cant = st.number_input("Cantidad", min_value=1)
            mot = st.selectbox("Motivo", ["Carga Incubadora", "Venta", "Merma"])
            if st.form_submit_button("🚀 PROCESAR SALIDA"):
                lote_info = lotes_disponibles[lotes_disponibles['id_unico'] == id_s].iloc[0]
                if cant <= lote_info['saldo']:
                    c.execute("UPDATE lotes SET saldo = saldo - ? WHERE id_unico = ?", (cant, id_s))
                    c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)", (id_s, lote_info['planta'], "SALIDA", cant, mot, datetime.now()))
                    conn.commit()
                    st.toast(f"Salida registrada: {id_s}", icon="📤")
                    st.success(f"✅ ¡Operación Exitosa! {cant} huevos retirados."); st.balloons(); time.sleep(1.5); st.rerun()
                else: st.error("Saldo insuficiente.")

# --- 🔍 5. FICHA DE TRAZABILIDAD (INTACTA) ---
elif choice == "🔍 Ficha de Trazabilidad":
    st.header("🔎 Expediente de Lote (Hoja de Vida)")
    lotes_todos = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
    target = st.selectbox("Buscar Lote:", ["Seleccionar..."] + lotes_todos['id_unico'].tolist())
    
    if target != "Seleccionar...":
        info = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{target}'", conn).iloc[0]
        movs = pd.read_sql_query(f"SELECT tipo, cantidad, motivo, fecha FROM historial WHERE id_lote='{target}' ORDER BY fecha DESC", conn)
        
        st.subheader("📊 Estado en Tiempo Real")
        m1, m2, m3, m4 = st.columns(4)
        with m1: st.markdown(f'<div class="info-card"><div class="info-label">Saldo en Cámara</div><div class="info-value">{info["saldo"]} Huevos</div></div>', unsafe_allow_html=True)
        with m2: st.markdown(f'<div class="info-card"><div class="info-label">Equivalencia</div><div class="info-value">{round(info["saldo"]/360, 1)} Cajas</div></div>', unsafe_allow_html=True)
        with m3: st.markdown(f'<div class="info-card"><div class="info-label">Días de Almacén</div><div class="info-value">{calcular_dias(info["fecha_postura"])} Días</div></div>', unsafe_allow_html=True)
        with m4: st.markdown(f'<div class="info-card"><div class="info-label">Edad Repro</div><div class="info-value">{info["edad_repro"] if info["edad_repro"] else "S/D"} Sem.</div></div>', unsafe_allow_html=True)

        st.subheader("📋 Datos Técnicos de Producción")
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(f'<div class="info-card"><div class="info-label">Granja</div><div class="info-value">{info["granja"]}</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="info-card"><div class="info-label">Línea Genética</div><div class="info-value">{info["linea_genetica"]}</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="info-card"><div class="info-label">Procedencia</div><div class="info-value">{info["procedencia"]}</div></div>', unsafe_allow_html=True)
        with c4: st.markdown(f'<div class="info-card"><div class="info-label">Lote Externo</div><div class="info-value">{info["lote_nro"]}</div></div>', unsafe_allow_html=True)

        st.warning(f"📝 **Observaciones Sanitarias:** {info['obs_sanitarias']}")
        st.divider()
        
        col_t1, col_t2 = st.columns([3, 1])
        col_t1.subheader("📜 Movimientos Registrados")
        if col_t2.download_button("📥 EXPORTAR EXPEDIENTE", to_excel(movs), f"Expediente_{target}.xlsx"):
            st.toast(f"Reporte de {target} descargado", icon="📄")
        st.dataframe(movs, use_container_width=True)

# --- 📜 HISTORIAL GENERAL (CON BUSCADORES) ---
elif choice == "📜 Historial General":
    st.header("📝 Auditoría de Movimientos")
    h_df = pd.read_sql_query("SELECT * FROM historial ORDER BY fecha DESC", conn)
    if not h_df.empty:
        # Fila de Buscadores
        h1, h2, h3 = st.columns(3)
        h_search = h1.text_input("🔍 Buscar Lote o ID:")
        h_tipo = h2.multiselect("Tipo Movimiento:", h_df['tipo'].unique(), default=h_df['tipo'].unique())
        h_planta = h3.multiselect("Filtrar Planta:", h_df['planta'].unique(), default=h_df['planta'].unique())
        
        # Aplicar filtros
        if h_search:
            h_df = h_df[h_df['id_lote'].str.contains(h_search, case=False)]
        h_df = h_df[(h_df['tipo'].isin(h_tipo)) & (h_df['planta'].isin(h_planta))]

        if st.download_button("📥 DESCARGAR HISTORIAL FILTRADO", to_excel(h_df), "Auditoria.xlsx"):
            st.toast("Auditoría exportada", icon="📜")
        st.dataframe(h_df, use_container_width=True)

st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
