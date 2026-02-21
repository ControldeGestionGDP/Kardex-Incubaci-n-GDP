import streamlit as st
import pandas as pd
from datetime import datetime, date
import sqlite3
import io

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="IncubaTrack ERP v4.3", page_icon="🥚", layout="wide")

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

# --- INTERFAZ ---
st.sidebar.title("🛠️ Panel de Control")
menu = ["🟢 Recepción", "🟡 Inventario Global", "📊 Seguimiento & Decisiones", "🔵 Salidas (Incubación)", "🔍 Ficha de Trazabilidad", "📜 Historial General"]
choice = st.sidebar.radio("Ir a:", menu)

# ---------------------------------------------------------
# 🟢 1. RECEPCIÓN
# ---------------------------------------------------------
if choice == "🟢 Recepción":
    st.header("📥 Registro de Lote")
    with st.form("form_ingreso", clear_on_submit=True):
        col1, col2 = st.columns(2)
        lote_input = col1.text_input("Número o Código de Lote", help="Solo números = CDG | SF = San Fernando | SE = Santa Elena")
        planta = col2.selectbox("Planta de Destino", ["P.I. Tarapoto", "P.I. Pucacaca"])
        
        c1, c2, c3 = st.columns(3)
        granja = c1.text_input("Granja")
        genetica = c2.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
        edad_repro = c3.number_input("Edad de Reproductora (Sem) - 0 = Sin Dato", min_value=0, value=0)
        
        c4, c5, c6 = st.columns(3)
        cant_h = c4.number_input("Cantidad de Huevos", min_value=0)
        f_postura = c5.date_input("Fecha de Postura")
        f_llegada = c6.date_input("Fecha de Llegada")
        
        transp = st.text_input("Transportista")
        obs = st.text_area("Observaciones")
        
        if st.form_submit_button("REGISTRAR INGRESO"):
            id_u, proc = generar_id_y_procedencia(lote_input)
            val_edad = edad_repro if edad_repro > 0 else None
            try:
                c.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (id_u, lote_input, proc, planta, granja, genetica, val_edad, f_postura, f_llegada, cant_h, cant_h, transp, obs))
                c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)",
                          (id_u, planta, "INGRESO", cant_h, "Recepción", datetime.now()))
                conn.commit()
                st.success(f"✅ Lote {id_u} registrado exitosamente")
                st.balloons()
            except: st.error("Error: El lote ya fue registrado hoy.")

# ---------------------------------------------------------
# 🟡 2. INVENTARIO GLOBAL
# ---------------------------------------------------------
elif choice == "🟡 Inventario Global":
    st.header("📦 Stock en Cámara Fría")
    df = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        col_f1, col_f2 = st.columns(2)
        f_proc = col_f1.multiselect("Procedencia:", df['procedencia'].unique(), default=df['procedencia'].unique())
        f_planta = col_f2.multiselect("Planta:", df['planta'].unique(), default=df['planta'].unique())
        df = df[(df['procedencia'].isin(f_proc)) & (df['planta'].isin(f_planta))]
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        df['Cajas (360)'] = (df['saldo'] / 360).round(2)
        df['edad_repro'] = df['edad_repro'].apply(lambda x: int(x) if pd.notnull(x) else "S/D")
        st.dataframe(df[['id_unico', 'planta', 'procedencia', 'lote_nro', 'saldo', 'Cajas (360)', 'Días Almacén', 'edad_repro', 'fecha_postura']], use_container_width=True)
        st.download_button("📊 Exportar Excel", to_excel(df), "Inventario_Actual.xlsx")
    else: st.info("No hay stock disponible.")

# ---------------------------------------------------------
# 📊 3. SEGUIMIENTO & DECISIONES
# ---------------------------------------------------------
elif choice == "📊 Seguimiento & Decisiones":
    st.header("🔬 Análisis de Prioridad")
    df_d = pd.read_sql_query("SELECT id_unico, planta, edad_repro, fecha_postura, saldo FROM lotes WHERE saldo > 0", conn)
    if not df_d.empty:
        df_d['Días Almacén'] = df_d['fecha_postura'].apply(calcular_dias)
        df_d['Cajas'] = (df_d['saldo'] / 360).round(1)
        def semaforo(row):
            if row['Días Almacén'] > 10: return "🔴 CRÍTICO"
            if pd.notnull(row['edad_repro']) and row['edad_repro'] > 60: return "🟠 REPRO VIEJA"
            if row['Días Almacén'] > 7: return "🟡 PRIORITARIO"
            return "🟢 ÓPTIMO"
        df_d['Estado'] = df_d.apply(semaforo, axis=1)
        st.dataframe(df_d[['id_unico', 'planta', 'Días Almacén', 'edad_repro', 'Cajas', 'Estado']].sort_values(by=['Días Almacén'], ascending=False), use_container_width=True)

# ---------------------------------------------------------
# 🔵 4. SALIDAS (INCUBACIÓN)
# ---------------------------------------------------------
elif choice == "🔵 Salidas (Incubación)":
    st.header("📤 Registrar Salida de Huevo")
    lotes_activos = pd.read_sql_query("SELECT id_unico, saldo, planta FROM lotes WHERE saldo > 0", conn)
    if not lotes_activos.empty:
        with st.form("form_salida"):
            col_s1, col_s2 = st.columns(2)
            id_salida = col_s1.selectbox("Seleccione el Lote", lotes_activos['id_unico'])
            saldo_actual = lotes_activos[lotes_activos['id_unico'] == id_salida]['saldo'].values[0]
            planta_lote = lotes_activos[lotes_activos['id_unico'] == id_salida]['planta'].values[0]
            cant_salida = col_s2.number_input(f"Cantidad a Salir (Máx: {saldo_actual})", min_value=1, max_value=int(saldo_actual), value=int(saldo_actual))
            motivo_salida = st.selectbox("Motivo de Salida", ["Carga a Incubadora", "Venta de Huevo", "Merma/Rotura", "Ajuste"])
            if st.form_submit_button("PROCESAR SALIDA"):
                c.execute("UPDATE lotes SET saldo = saldo - ? WHERE id_unico = ?", (cant_salida, id_salida))
                c.execute("INSERT INTO historial (id_lote, planta, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?,?)",
                          (id_salida, planta_lote, "SALIDA", cant_salida, motivo_salida, datetime.now()))
                conn.commit()
                st.success("✅ Salida registrada")
                st.rerun()
    else: st.warning("No hay huevos en stock.")

# ---------------------------------------------------------
# 🔍 5. FICHA DE TRAZABILIDAD
# ---------------------------------------------------------
elif choice == "🔍 Ficha de Trazabilidad":
    st.header("🧐 Detalle por Lote")
    lotes_todos = pd.read_sql_query("SELECT id_unico FROM lotes", conn)
    target = st.selectbox("Lote:", ["Seleccionar..."] + lotes_todos['id_unico'].tolist())
    if target != "Seleccionar...":
        info = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{target}'", conn).iloc[0]
        movs = pd.read_sql_query(f"SELECT tipo, cantidad, motivo, fecha FROM historial WHERE id_lote='{target}'", conn)
        st.metric("Saldo Actual", f"{info['saldo']} huevos ({round(info['saldo']/360,1)} cajas)")
        st.write(f"**Procedencia:** {info['procedencia']} | **Transportista:** {info['transportista']}")
        st.dataframe(movs, use_container_width=True)

# ---------------------------------------------------------
# 📜 6. HISTORIAL GENERAL
# ---------------------------------------------------------
elif choice == "📜 Historial General":
    st.header("📋 Movimientos de Planta")
    h_df = pd.read_sql_query("SELECT id_lote, planta, tipo, cantidad, motivo, fecha FROM historial ORDER BY fecha DESC", conn)
    st.dataframe(h_df, use_container_width=True)
