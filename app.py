import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3
import io

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="IncubaTrack PRO v3", page_icon="🐣", layout="wide")

# --- CONEXIÓN A BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('incubacion_pro_v3.db', check_same_thread=False)
    c = conn.cursor()
    # Tabla de Lotes
    c.execute('''CREATE TABLE IF NOT EXISTS lotes (
                    id_unico TEXT PRIMARY KEY, lote_nro TEXT, planta TEXT, 
                    granja TEXT, linea_genetica TEXT, edad_repro INTEGER, 
                    fecha_postura DATE, fecha_llegada DATE, cantidad_inicial INTEGER, 
                    saldo INTEGER, cajas REAL, transportista TEXT, obs_sanitarias TEXT)''')
    # Tabla de Historial de Movimientos
    c.execute('''CREATE TABLE IF NOT EXISTS historial (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, id_lote TEXT, 
                    tipo TEXT, cantidad INTEGER, motivo TEXT, fecha TIMESTAMP)''')
    conn.commit()
    return conn

conn = init_db()
c = conn.cursor()

# --- FUNCIONES ---
def generar_id(lote_nro):
    # Si el lote es numérico, es CDG
    prefijo = "CDG" if lote_nro.isdigit() else "LOTE"
    fecha_hoy = datetime.now().strftime("%d%m%Y")
    return f"{prefijo}-{lote_nro}-{fecha_hoy}"

def calcular_almacen(f_postura):
    if isinstance(f_postura, str):
        f_postura = datetime.strptime(f_postura, '%Y-%m-%d').date()
    return (datetime.now().date() - f_postura).days

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Kardex')
    return output.getvalue()

# --- INTERFAZ ---
st.title("🐣 IncubaTrack PRO | Gestión de Almacenes")
st.markdown(f"**Fecha actual:** {datetime.now().strftime('%d/%m/%Y')}")

menu = ["🟢 Recepción & Edición", "🟡 Inventario Actual", "🔵 Salidas e Historial"]
choice = st.sidebar.radio("Navegación Principal", menu)

# ---------------------------------------------------------
# 🟢 1. RECEPCIÓN & EDICIÓN
# ---------------------------------------------------------
if choice == "🟢 Recepción & Edición":
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📦 Registro de Ingreso")
        with st.form("form_registro", clear_on_submit=True):
            planta = st.selectbox("Planta de Incubación (P.I.)", ["P.I. Tarapoto", "P.I. Pucacaca"])
            lote_nro = st.text_input("Número de Lote (ej: 224 o A-15)")
            granja = st.text_input("Granja")
            linea = st.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard"])
            
            c_f1, c_f2 = st.columns(2)
            f_postura = c_f1.date_input("Fecha Postura")
            f_llegada = c_f2.date_input("Fecha Llegada")
            
            c_n1, c_n2 = st.columns(2)
            cant = c_n1.number_input("Cant. Huevos", min_value=0)
            cajas = c_n2.number_input("Cajas", min_value=0.0)
            
            transp = st.text_input("Transportista")
            obs = st.text_area("Observaciones Sanitarias")
            
            if st.form_submit_button("REGISTRAR"):
                nuevo_id = generar_id(lote_nro)
                try:
                    c.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (nuevo_id, lote_nro, planta, granja, linea, 0, f_postura, 
                               f_llegada, cant, cant, cajas, transp, obs))
                    c.execute("INSERT INTO historial (id_lote, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?)",
                              (nuevo_id, "INGRESO", cant, "Recepción en Planta", datetime.now()))
                    conn.commit()
                    st.success(f"Registrado como: {nuevo_id}")
                    st.rerun()
                except:
                    st.error("Este ID ya fue registrado hoy. Verifica el número de lote.")

    with col2:
        st.subheader("📝 Editar Registro")
        lotes_edit = pd.read_sql_query("SELECT id_unico FROM lotes WHERE saldo > 0", conn)
        if not lotes_edit.empty:
            sel_id = st.selectbox("ID a editar", lotes_edit)
            datos = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{sel_id}'", conn).iloc[0]
            with st.expander("Modificar datos"):
                edit_saldo = st.number_input("Corregir Saldo", value=int(datos['saldo']))
                edit_obs = st.text_area("Actualizar Obs.", datos['obs_sanitarias'])
                if st.button("Guardar Cambios"):
                    c.execute("UPDATE lotes SET saldo=?, obs_sanitarias=? WHERE id_unico=?", (edit_saldo, edit_obs, sel_id))
                    conn.commit()
                    st.success("Actualizado")
                    st.rerun()

# ---------------------------------------------------------
# 🟡 2. INVENTARIO ACTUAL
# ---------------------------------------------------------
elif choice == "🟡 Inventario Actual":
    st.header("Inventario de Huevos Incubables")
    
    filtro_planta = st.multiselect("Filtrar por Planta:", ["P.I. Tarapoto", "P.I. Pucacaca"], default=["P.I. Tarapoto", "P.I. Pucacaca"])
    
    df = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    if not df.empty:
        df = df[df['planta'].isin(filtro_planta)]
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_almacen)
        
        # Orden de columnas
        cols = ['id_unico', 'planta', 'lote_nro', 'Días Almacén', 'saldo', 'cajas', 'granja', 'linea_genetica', 'fecha_postura', 'transportista', 'obs_sanitarias']
        df_final = df[cols]

        def color_alert(row):
            styles = [''] * len(row)
            if row['Días Almacén'] > 10: styles = ['background-color: #f8d7da'] * len(row)
            elif row['Días Almacén'] > 7: styles = ['background-color: #fff3cd'] * len(row)
            return styles

        st.dataframe(df_final.style.apply(color_alert, axis=1), use_container_width=True)
        st.download_button("📥 Descargar Excel", to_excel(df_final), "Kardex_PRO.xlsx")
    else:
        st.info("Sin stock.")

# ---------------------------------------------------------
# 🔵 3. SALIDAS E HISTORIAL
# ---------------------------------------------------------
elif choice == "🔵 Salidas e Historial":
    st.subheader("📤 Registrar Salida")
    df_s = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    
    if not df_s.empty:
        with st.expander("Nueva Salida a Incubación / Merma"):
            lote_s = st.selectbox("Seleccione Lote", df_s['id_unico'])
            c_s1, c_s2 = st.columns(2)
            cant_s = c_s1.number_input("Cantidad", min_value=1)
            motivo = c_s2.selectbox("Destino/Motivo", ["Incubadora", "Merma", "Venta", "Ajuste"])
            
            if st.button("Confirmar Salida"):
                saldo_act = df_s[df_s['id_unico'] == lote_s]['saldo'].values[0]
                if cant_s <= saldo_act:
                    nuevo_s = int(saldo_act - cant_s)
                    c.execute("UPDATE lotes SET saldo=? WHERE id_unico=?", (nuevo_s, lote_s))
                    c.execute("INSERT INTO historial (id_lote, tipo, cantidad, motivo, fecha) VALUES (?,?,?,?,?)",
                              (lote_s, "SALIDA", cant_s, motivo, datetime.now()))
                    conn.commit()
                    st.success("Movimiento registrado")
                    st.rerun()
                else:
                    st.error("Saldo insuficiente")

    st.markdown("---")
    st.subheader("📜 Historial General de Movimientos")
    hist_df = pd.read_sql_query("SELECT * FROM historial ORDER BY fecha DESC", conn)
    st.dataframe(hist_df, use_container_width=True)
