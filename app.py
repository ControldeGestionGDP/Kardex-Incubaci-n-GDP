import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="IncubaTrack PRO", 
    page_icon="🐣", 
    layout="wide"
)

# --- ESTILOS PERSONALIZADOS ---
st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- BASE DE DATOS (SQLite) ---
def init_db():
    conn = sqlite3.connect('sistema_incubacion.db', check_same_thread=False)
    c = conn.cursor()
    # Tabla de Lotes
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
                    nivel TEXT
                )''')
    # Tabla de Movimientos (Historial)
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_unico TEXT,
                    tipo TEXT,
                    cantidad INTEGER,
                    destino_motivo TEXT,
                    fecha TIMESTAMP
                )''')
    conn.commit()
    return conn

conn = init_db()
c = conn.cursor()

# --- FUNCIONES DE CÁLCULO ---
def get_edad_huevo(fecha_postura):
    if isinstance(fecha_postura, str):
        fecha_postura = datetime.strptime(fecha_postura, '%Y-%m-%d').date()
    return (datetime.now().date() - fecha_postura).days

# --- INTERFAZ DE USUARIO ---
st.title("🐣 Sistema de Control de Incubación PRO")
st.caption("Gestión avanzada de trazabilidad y almacenamiento de huevos incubables")

# --- 📊 DASHBOARD (MÉTRICAS) ---
df_actual = pd.read_sql_query("SELECT * FROM lotes WHERE saldo > 0", conn)
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_huevos = df_actual['saldo'].sum() if not df_actual.empty else 0
    st.metric("Total Huevos en Stock", f"{total_huevos:,}")
with col2:
    st.metric("Lotes Activos", len(df_actual))
with col3:
    # Alerta sobretiempo (>7 días)
    riesgo = 0
    if not df_actual.empty:
        edades = df_actual['fecha_postura'].apply(get_edad_huevo)
        riesgo = len(edades[edades > 7])
    st.metric("Lotes en Riesgo (>7d)", riesgo)
with col4:
    # Críticos (>10 días)
    criticos = 0
    if not df_actual.empty:
        edades = df_actual['fecha_postura'].apply(get_edad_huevo)
        criticos = len(edades[edades > 10])
    st.metric("Críticos (>10d)", criticos)

st.divider()

# --- NAVEGACIÓN ---
menu = ["🟢 Recepción", "🟡 Almacén & Inventario", "🔵 Transferencias e Historial"]
choice = st.sidebar.radio("Módulos del Sistema", menu)

# ---------------------------------------------------------
# 🟢 1. RECEPCIÓN DE HUEVOS
# ---------------------------------------------------------
if choice == "🟢 Recepción":
    st.header("Registro de Ingreso (Recepción)")
    
    with st.form("form_recepcion", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        lote_nro = c1.text_input("Número de Lote")
        granja = c2.text_input("Granja de Origen")
        linea = c3.selectbox("Línea Genética", ["Cobb 500", "Ross 308", "Hubbard", "Hy-Line"])
        
        c4, c5, c6 = st.columns(3)
        edad_repro = c4.number_input("Edad Reproductoras (Sem)", min_value=0)
        f_postura = c5.date_input("Fecha de Postura")
        f_llegada = c6.date_input("Fecha de Llegada (Planta)")
        
        c7, c8, c9 = st.columns(3)
        cantidad = c7.number_input("Cantidad de Huevos", min_value=0)
        cajas = c8.number_input("Cantidad de Cajas", min_value=0.0)
        temp = c9.number_input("Temperatura Arribo (°C)", format="%.1f")
        
        st.markdown("### Ubicación y Logística")
        c10, c11, c12, c13 = st.columns(4)
        camara = c10.text_input("Cámara / Sala")
        rack = c11.text_input("Rack")
        nivel = c12.text_input("Nivel")
        transp = c13.text_input("Transportista")
        
        obs = st.text_area("Observaciones Sanitarias / Calidad")
        
        if st.form_submit_button("REGISTRAR INGRESO"):
            # Generar ID Único
            id_u = f"{lote_nro}-{datetime.now().strftime('%M%S')}"
            
            try:
                c.execute('''INSERT INTO lotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (id_u, lote_nro, granja, linea, edad_repro, f_postura, f_llegada, 
                           cantidad, cantidad, cajas, temp, transp, obs, camara, rack, nivel))
                
                # Registrar movimiento inicial
                c.execute("INSERT INTO movimientos (id_unico, tipo, cantidad, destino_motivo, fecha) VALUES (?,?,?,?,?)",
                          (id_u, "INGRESO", cantidad, "Recepción Inicial", datetime.now()))
                
                conn.commit()
                st.success(f"✅ Lote {id_u} registrado y almacenado correctamente.")
                st.balloons()
            except Exception as e:
                st.error(f"Error al registrar: {e}")

# ---------------------------------------------------------
# 🟡 2. ALMACÉN DE HUEVOS
# ---------------------------------------------------------
elif choice == "🟡 Almacén & Inventario":
    st.header("Inventario Actual en Cámaras")
    
    if df_actual.empty:
        st.warning("No hay huevos en inventario.")
    else:
        # Procesar datos para visualización
        df_view = df_actual.copy()
        df_view['Días Almacenados'] = df_view['fecha_llegada'].apply(lambda x: (datetime.now().date() - datetime.strptime(x, '%Y-%m-%d').date()).days)
        df_view['Edad Huevo (Días)'] = df_view['fecha_postura'].apply(get_edad_huevo)
        
        # Formato de tabla profesional
        def highlight_age(val):
            color = 'white'
            if val > 10: color = '#f8d7da' # Rojo crítico
            elif val > 7: color = '#fff3cd' # Amarillo riesgo
            return f'background-color: {color}'

        st.dataframe(
            df_view[['id_unico', 'lote_nro', 'granja', 'linea_genetica', 'saldo', 'camara', 'rack', 'nivel', 'Edad Huevo (Días)', 'Días Almacenados']]
            .style.applymap(highlight_age, subset=['Edad Huevo (Días)']),
            use_container_width=True
        )
        
        st.info("💡 **Leyenda:** Fondo Amarillo (>7 días) | Fondo Rojo (>10 días).")

# ---------------------------------------------------------
# 🔵 3. TRANSFERENCIAS E HISTORIAL
# ---------------------------------------------------------
elif choice == "🔵 Transferencias e Historial":
    st.header("Movimientos Internos y Salidas")
    
    tab_mov, tab_hist = st.tabs(["Realizar Movimiento", "Historial Completo"])
    
    with tab_mov:
        if df_actual.empty:
            st.info("No hay lotes disponibles para mover.")
        else:
            with st.form("form_mov"):
                lote_sel = st.selectbox("Seleccione Lote", df_actual['id_unico'].tolist())
                c1, c2 = st.columns(2)
                tipo_m = c1.selectbox("Tipo de Movimiento", ["Salida a Incubación", "Merma/Clasificación", "Ajuste de Inventario", "Eliminación Sanitaria"])
                cant_m = c2.number_input("Cantidad de Huevos", min_value=1)
                destino = st.text_input("Destino / Motivo (Ej: Incubadora 4, Roto, etc.)")
                
                if st.form_submit_button("Confirmar Movimiento"):
                    # Validar Saldo
                    saldo_actual = df_actual[df_actual['id_unico'] == lote_sel]['saldo'].values[0]
                    
                    if cant_m <= saldo_actual:
                        nuevo_saldo = int(saldo_actual - cant_m)
                        # Actualizar Lote
                        c.execute("UPDATE lotes SET saldo = ? WHERE id_unico = ?", (nuevo_saldo, lote_sel))
                        # Registrar Movimiento
                        c.execute("INSERT INTO movimientos (id_unico, tipo, cantidad, destino_motivo, fecha) VALUES (?,?,?,?,?)",
                                  (lote_sel, tipo_m, cant_m, destino, datetime.now()))
                        conn.commit()
                        st.success("Movimiento registrado con éxito.")
                        st.rerun()
                    else:
                        st.error("Error: La cantidad supera el saldo disponible.")

    with tab_hist:
        hist_df = pd.read_sql_query("SELECT * FROM movimientos ORDER BY fecha DESC", conn)
        st.table(hist_df)
