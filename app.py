import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3
import io

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="IncubaTrack PRO v2", page_icon="🐣", layout="wide")

# --- CONEXIÓN A BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('incubacion_v2.db', check_same_thread=False)
    c = conn.cursor()
    # Tabla con todos los campos de recepción
    c.execute('''CREATE TABLE IF NOT EXISTS lotes (
                    id_unico TEXT PRIMARY KEY, 
                    lote_nro TEXT, 
                    granja TEXT, 
                    linea_genetica TEXT, 
                    edad_repro INTEGER, 
                    fecha_postura DATE, 
                    fecha_llegada DATE, 
                    cantidad_inicial INTEGER, 
                    saldo INTEGER, 
                    cajas REAL, 
                    temp_arribo REAL, 
                    transportista TEXT, 
                    obs_sanitarias TEXT, 
                    camara TEXT, 
                    rack TEXT, 
                    nivel TEXT)''')
    conn.commit()
    return conn

conn = init_db()
c = conn.cursor()

# --- FUNCIONES CRÍTICAS ---
def calcular_dias_almacen(fecha_postura):
    # Convierte string de BD a objeto fecha si es necesario
    if isinstance(fecha_postura, str):
        f_postura = datetime.strptime(fecha_postura, '%Y-%m-%d').date()
    else:
        f_postura = fecha_postura
    return (datetime.now().date() - f_postura).days

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario_Pro')
        # Formateo automático de ancho de columnas
        worksheet = writer.sheets['Inventario_Pro']
        for i, col in enumerate(df.columns):
            column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
            worksheet.set_column(i, i, column_len)
    return output.getvalue()

# --- INTERFAZ STREAMLIT ---
st.title("🚀 IncubaTrack PRO | Gestión de Planta")
st.markdown("Sistema de trazabilidad desde postura hasta incubación")

menu = ["🟢 Recepción & Edición", "🟡 Almacén (Full Data)", "🔵 Salidas e Historial"]
choice = st.sidebar.radio("Navegación", menu)

# ---------------------------------------------------------
# 🟢 1. RECEPCIÓN & EDICIÓN
# ---------------------------------------------------------
if choice == "🟢 Recepción & Edición":
    col_form, col_edit = st.columns([1, 1])
    
    with col_form:
        st.subheader("📦 Registro de Nuevo Lote")
        with st.form("form_registro", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            lote_nro = c1.text_input("Número de Lote")
            granja = c2.text_input("Granja de Origen")
            linea = c3.selectbox("Línea Genética", ["Cobb 500", "Ross 308", "Hubbard", "Hy-Line"])
            
            c4, c5, c6 = st.columns(3)
            edad_repro = c4.number_input("Edad Repro (Sem)", min_value=0)
            f_postura = c5.date_input("Fecha de Postura")
            f_llegada = c6.date_input("Fecha Llegada a Planta")
            
            c7, c8, c9 = st.columns(3)
            cant = c7.number_input("Cantidad Huevos", min_value=0)
            cajas = c8.number_input("Total Cajas", min_value=0.0)
            temp = c9.number_input("Temp Arribo °C", format="%.1f")
            
            st.markdown("---")
            c10, c11, c12 = st.columns(3)
            cam = c10.text_input("Cámara")
            rack = c11.text_input("Rack")
            niv = c12.text_input("Nivel")
            
            transp = st.text_input("Transportista / Chofer")
            obs = st.text_area("Observaciones Sanitarias")
            
            if st.form_submit_button("REGISTRAR INGRESO"):
                id_u = f"LOT-{lote_nro}-{datetime.now().strftime('%H%M%S')}"
                c.execute("INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (id_u, lote_nro, granja, linea, edad_repro, f_postura, f_llegada, 
                           cant, cant, cajas, temp, transp, obs, cam, rack, niv))
                conn.commit()
                st.success(f"Lote {id_u} guardado en base de datos.")
                st.rerun()

    with col_edit:
        st.subheader("📝 Panel de Edición")
        lotes_activos = pd.read_sql_query("SELECT id_unico, lote_nro FROM lotes WHERE saldo > 0", conn)
        if not lotes_activos.empty:
            lote_id = st.selectbox("Seleccione el ID para corregir", lotes_activos['id_unico'])
            datos = pd.read_sql_query(f"SELECT * FROM lotes WHERE id_unico='{lote_id}'", conn).iloc[0]
            
            with st.expander("Modificar campos del lote"):
                edit_lote = st.text_input("Corregir # Lote", datos['lote_nro'])
                edit_saldo = st.number_input("Corregir Saldo Huevos", value=int(datos['saldo']))
                edit_cam = st.text_input("Cambiar Cámara", datos['camara'])
                edit_obs = st.text_area("Actualizar Observaciones", datos['obs_sanitarias'])
                
                if st.button("Guardar Cambios"):
                    c.execute("UPDATE lotes SET lote_nro=?, saldo=?, camara=?, obs_sanitarias=? WHERE id_unico=?", 
                              (edit_lote, edit_saldo, edit_cam, edit_obs, lote_id))
                    conn.commit()
                    st.success("Información actualizada correctamente.")
                    st.rerun()

# ---------------------------------------------------------
# 🟡 2. ALMACÉN (FULL DATA)
# ---------------------------------------------------------
elif choice == "🟡 Almacén (Full Data)":
    st.header("Inventario de Huevos en Cámara Fría")
    df = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    
    if not df.empty:
        # Cálculo de días (Desde postura hasta hoy)
        df['Días Almacén (Total)'] = df['fecha_postura'].apply(calcular_dias_almacen)
        
        # Seleccionar y ordenar todas las columnas según tu pedido
        cols_ordenadas = [
            'id_unico', 'lote_nro', 'granja', 'linea_genetica', 'Días Almacén (Total)', 
            'saldo', 'cajas', 'fecha_postura', 'fecha_llegada', 'edad_repro', 
            'temp_arribo', 'camara', 'rack', 'nivel', 'transportista', 'obs_sanitarias'
        ]
        df_final = df[cols_ordenadas]

        # Alertas Visuales
        def style_rows(row):
            styles = [''] * len(row)
            if row['Días Almacén (Total)'] > 10:
                styles = ['background-color: #f8d7da; color: #721c24'] * len(row)
            elif row['Días Almacén (Total)'] > 7:
                styles = ['background-color: #fff3cd; color: #856404'] * len(row)
            return styles

        st.dataframe(df_final.style.apply(style_rows, axis=1), use_container_width=True)
        
        # Botón Excel con xlsxwriter
        excel_data = to_excel(df_final)
        st.download_button(
            label="📊 Descargar Inventario Completo (Excel)",
            data=excel_data,
            file_name=f'Kardex_Incubacion_{datetime.now().strftime("%Y-%m-%d")}.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        st.info("No hay lotes con saldo positivo actualmente.")

# ---------------------------------------------------------
# 🔵 3. SALIDAS E HISTORIAL
# ---------------------------------------------------------
elif choice == "🔵 Salidas e Historial":
    st.header("Gestión de Salidas (Incubación/Mermas)")
    df_act = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
    
    if not df_act.empty:
        with st.container(border=True):
            lote_sel = st.selectbox("Seleccione el Lote para procesar", df_act['id_unico'])
            c1, c2 = st.columns(2)
            cant_s = c1.number_input("Cantidad de Huevos a retirar", min_value=1)
            motivo = c2.selectbox("Motivo de Salida", ["Carga Incubadora", "Merma Sanitaria", "Rotura en Planta", "Ajuste"])
            
            if st.button("Confirmar Movimiento"):
                saldo_actual = df_act[df_act['id_unico'] == lote_sel]['saldo'].values[0]
                if cant_s <= saldo_actual:
                    nuevo_saldo = int(saldo_actual - cant_s)
                    c.execute("UPDATE lotes SET saldo = ? WHERE id_unico = ?", (nuevo_saldo, lote_sel))
                    conn.commit()
                    st.success(f"Salida procesada. Saldo restante: {nuevo_saldo}")
                    st.rerun()
                else:
                    st.error("No puedes retirar más huevos de los que hay en stock.")
