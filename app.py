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
    height: 100%;
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
        lotes_ws.update_cell(row_number, col_index, int(nuevo_saldo))

# --- LÓGICA DE NEGOCIO ---
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
        try:
            f_postura = datetime.strptime(f_postura, "%Y-%m-%d").date()
        except:
            return 0
    return (date.today() - f_postura).days

def clasificar_repro(edad):
    if not edad or edad == 0: return "S/D"
    if edad < 30: return "Joven (<30)"
    if 30 <= edad <= 39: return "Óptima (30-39)"
    if 40 <= edad <= 49: return "Madura (40-49)"
    return "Vieja (≥50)"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- SIDEBAR ---
st.sidebar.markdown('<div class="sidebar-logo">🐣</div>', unsafe_allow_html=True)
st.sidebar.title("MENU ERP")
menu = ["🟢 Recepción", "🟡 Inventario Global", "📊 Seguimiento & Decisiones", "🔵 Salidas (Incubación)", "🔍 Ficha de Trazabilidad", "📜 Historial General"]
choice = st.sidebar.radio("Navegación:", menu)

# -------------------- RECEPCIÓN --------------------
if choice == "🟢 Recepción":
    t1, t2 = st.tabs(["📥 Nuevo Ingreso", "✏️ Editar/Corregir"])
    with t1:
        st.header("Registro de Ingresos")
        with st.form("form_ingreso", clear_on_submit=True):
            col1, col2 = st.columns(2)
            lote_input = col1.text_input("Nro de Lote")
            planta = col2.selectbox("Planta Destino", ["P.I. Tarapoto", "P.I. Pucacaca"])
            
            c1, c2 = st.columns(2)
            # --- GRANJA ELIMINADA ---
            descripcion = c1.selectbox("Descripción", ["Huevo Incubable Premium", "Huevo Incubable No Premium"])
            genetica = c2.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
            
            c3, c4, c5 = st.columns(3)
            edad_repro = c3.number_input("Edad Repro", min_value=0)
            cant_h = c4.number_input("Cantidad", min_value=0)
            f_postura = c5.date_input("Fecha Postura")
            
            f_llegada = st.date_input("Fecha Llegada")
            obs = st.text_area("Notas Sanitarias")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                if not lote_input:
                    st.error("El número de lote es obligatorio")
                else:
                    id_u, proc = generar_id_y_procedencia(lote_input)
                    # --- FILA AJUSTADA (Sin Granja) ---
                    # [id_u, lote, proc, planta, descripcion, genetica, edad, posture, llegada, inicial, saldo, obs]
                    insertar_lote([id_u, lote_input, proc, planta, descripcion, genetica, edad_repro, str(f_postura), str(f_llegada), cant_h, cant_h, obs])
                    insertar_movimiento(["", id_u, planta, "INGRESO", cant_h, f"Recepción: {descripcion}", str(datetime.now())])
                    st.success(f"Lote {id_u} registrado")
                    lluvia_de_pollitos()
                    st.rerun()
    with t2:
        st.header("Editor de Lotes")
        df_lotes = cargar_lotes()
        
        # Filtramos para no mostrar IDs vacíos si los hubiera
        lista_ids = ["Seleccionar..."] + df_lotes['id_unico'].dropna().tolist()
        id_edit = st.selectbox("Seleccione ID para modificar o eliminar:", lista_ids)
        
        if id_edit != "Seleccionar...":
            datos = df_lotes[df_lotes["id_unico"]==id_edit].iloc[0]
            
            with st.form("f_edit"):
                col_e1, col_e2 = st.columns(2)
                # --- GRANJA ELIMINADA ---
                e_desc = col_e1.selectbox("Descripción", ["Huevo Incubable Premium", "Huevo Incubable No Premium"], 
                                         index=0 if datos['descripcion']=="Huevo Incubable Premium" else 1)
                e_planta = col_e2.selectbox("Planta", ["P.I. Tarapoto", "P.I. Pucacaca"], 
                                           index=0 if datos['planta']=="P.I. Tarapoto" else 1)
                
                col_f1, col_f2 = st.columns(2)
                e_f_postura = col_f1.date_input("Fecha Postura", value=pd.to_datetime(datos['fecha_postura']).date())
                e_f_llegada = col_f2.date_input("Fecha Llegada", value=pd.to_datetime(datos['fecha_llegada']).date())
                
                ce1, ce2, ce3 = st.columns(3)
                # Manejo de error si la genética no está en la lista predefinida
                opciones_gen = ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"]
                idx_gen = opciones_gen.index(datos['linea_genetica']) if datos['linea_genetica'] in opciones_gen else 3
                
                e_gen = ce1.selectbox("Genética", opciones_gen, index=idx_gen)
                e_edad = ce2.number_input("Edad Repro", value=int(datos['edad_repro']))
                e_saldo = ce3.number_input("Saldo", value=int(datos['saldo']))
                
                e_obs = st.text_area("Observaciones", value=datos['obs_sanitarias'])
                
                if st.form_submit_button("🔄 ACTUALIZAR DATOS"):
                    headers = df_lotes.columns.tolist()
                    fila_idx = df_lotes[df_lotes['id_unico']==id_edit].index[0] + 2
                    update_dict = {
                        'planta': e_planta,
                        'descripcion': e_desc,
                        'linea_genetica': e_gen,
                        'edad_repro': e_edad,
                        'fecha_postura': str(e_f_postura),
                        'fecha_llegada': str(e_f_llegada),
                        'saldo': e_saldo,
                        'obs_sanitarias': e_obs
                    }
                    # Actualización celda por celda para mayor seguridad
                    for col_name, val in update_dict.items():
                        if col_name in headers:
                            col_idx = headers.index(col_name) + 1
                            lotes_ws.update_cell(fila_idx, col_idx, str(val))
                    
                    st.toast(f"Lote {id_edit} actualizado correctamente")
                    time.sleep(1)
                    st.rerun()

            # --- SECCIÓN DE ELIMINACIÓN SEGURA ---
            st.markdown("---")
            with st.expander("⚠️ ZONA DE PELIGRO - Borrar Registro"):
                st.warning(f"¿Estás seguro de que deseas eliminar el lote **{id_edit}**? Esta acción no se puede deshacer y eliminará la fila de la base de datos.")
                confirmar_check = st.checkbox("Confirmo que deseo borrar este registro permanentemente.")
                
                if st.button("🗑️ ELIMINAR INGRESO AHORA"):
                    if confirmar_check:
                        # Buscamos la fila nuevamente para asegurar precisión antes de borrar
                        df_actual = cargar_lotes()
                        filas_encontradas = df_actual[df_actual['id_unico'] == id_edit].index
                        
                        if not filas_encontradas.empty:
                            fila_a_borrar = filas_encontradas[0] + 2
                            lotes_ws.delete_rows(int(fila_a_borrar))
                            
                            st.error(f"Registro {id_edit} eliminado de la base de datos.")
                            lluvia_de_pollitos()
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error("No se pudo encontrar el ID para borrar.")
                    else:
                        st.info("Debes marcar la casilla de confirmación para poder eliminar.")

# -------------------- INVENTARIO --------------------
elif choice == "🟡 Inventario Global":
    st.header("Consolidado de Stock")
    df = cargar_lotes()
    if not df.empty:
        df = df[df["saldo"]>0].copy()
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)
        # --- GRANJA ELIMINADA DE LA VISTA ---
        cols_view = ['id_unico', 'lote_nro', 'descripcion', 'planta', 'saldo', 'Días Almacén']
        st.dataframe(df[cols_view], use_container_width=True)
        st.download_button("📥 DESCARGAR EXCEL", to_excel(df), "Inventario_Filtrado.xlsx")

# -------------------- SEGUIMIENTO Y DECISIONES --------------------
elif choice == "📊 Seguimiento & Decisiones":
    st.header("Seguimiento y Clasificación")
    df = cargar_lotes()
    if not df.empty:
        df = df[df["saldo"]>0].copy()
        df['Días'] = df['fecha_postura'].apply(calcular_dias)
        df['Clasif. Repro'] = df['edad_repro'].apply(clasificar_repro)
        df = df.sort_values(by="Días", ascending=False)
        def color_semaforo(row):
            if row['Días'] > 10: return ['background-color: #ffcccc']*len(row)
            elif 7<=row['Días']<=9: return ['background-color: #fff4cc']*len(row)
            else: return ['background-color: #d4edda']*len(row)
        # --- GRANJA ELIMINADA DE LA VISTA ---
        cols_viz = ['id_unico', 'descripcion', 'planta', 'Días', 'Clasif. Repro', 'saldo']
        st.dataframe(df[cols_viz].style.apply(color_semaforo, axis=1), use_container_width=True)

# -------------------- SALIDAS --------------------
elif choice == "🔵 Salidas (Incubación)":
    st.header("Orden de Salida")
    df = cargar_lotes()
    df = df[df["saldo"]>0]
    if not df.empty:
        with st.form("form_salida", clear_on_submit=True):
            id_s = st.selectbox("Seleccione Lote", df["id_unico"])
            cant = st.number_input("Cantidad", min_value=1)
            mot = st.selectbox("Motivo", ["Carga Incubadora", "Venta", "Merma"])
            if st.form_submit_button("🚀 PROCESAR SALIDA"):
                lote_info = df[df["id_unico"]==id_s].iloc[0]
                if cant<=lote_info['saldo']:
                    nuevo_saldo = lote_info['saldo'] - cant
                    actualizar_saldo(id_s, nuevo_saldo)
                    insertar_movimiento(["", id_s, lote_info["planta"], "SALIDA", cant, mot, str(datetime.now())])
                    st.success(f"Salida registrada")
                    lluvia_de_pollitos()
                    st.rerun()
                else: st.error("Saldo insuficiente")

# -------------------- FICHA DE TRAZABILIDAD --------------------
elif choice == "🔍 Ficha de Trazabilidad":
    st.header("Expediente de Lote")
    df = cargar_lotes()
    target = st.selectbox("Buscar Lote:", ["Seleccionar..."] + df['id_unico'].tolist())
    if target != "Seleccionar...":
        info = df[df['id_unico']==target].iloc[0]
        st.subheader("Estado en Tiempo Real")
        m1,m2,m3,m4 = st.columns(4)
        with m1: st.markdown(f'<div class="info-card"><div class="info-label">Saldo en Cámara</div><div class="info-value">{info["saldo"]} Huevos</div></div>', unsafe_allow_html=True)
        with m2: st.markdown(f'<div class="info-card"><div class="info-label">Equivalencia</div><div class="info-value">{round(info["saldo"]/360,1)} Cajas</div></div>', unsafe_allow_html=True)
        with m3: st.markdown(f'<div class="info-card"><div class="info-label">Días de Almacén</div><div class="info-value">{calcular_dias(info["fecha_postura"])} Días</div></div>', unsafe_allow_html=True)
        with m4: st.markdown(f'<div class="info-card"><div class="info-label">Descripción</div><div class="info-value">{info["descripcion"]}</div></div>', unsafe_allow_html=True)
        
        st.subheader("Datos Técnicos de Producción")
        c1,c2,c3 = st.columns(3)
        # --- GRANJA ELIMINADA DE AQUÍ TAMBIÉN ---
        with c1: st.markdown(f'<div class="info-card"><div class="info-label">Línea Genética</div><div class="info-value">{info["linea_genetica"]}</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="info-card"><div class="info-label">Procedencia</div><div class="info-value">{info["procedencia"]}</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="info-card"><div class="info-label">Lote Externo</div><div class="info-value">{info["lote_nro"]}</div></div>', unsafe_allow_html=True)
        st.warning(f" **Observaciones Sanitarias:** {info['obs_sanitarias']}")
        st.divider()
        movs = cargar_movimientos()
        movs = movs[movs['id_lote']==target].sort_values(by="fecha", ascending=False)
        st.dataframe(movs, use_container_width=True)

# -------------------- HISTORIAL GENERAL --------------------
elif choice == "📜 Historial General":
    st.header("Auditoría de Movimientos")
    
    with st.spinner("Cargando historial desde el Hub..."):
        h_df = cargar_movimientos()
    
    if not h_df.empty:
        # --- FILTROS DE AUDITORÍA ---
        col_f1, col_f2 = st.columns([1, 2])
        with col_f1:
            tipos = ["Todos"] + h_df['tipo'].unique().tolist()
            filtro_tipo = st.selectbox("Filtrar por movimiento:", tipos)
        
        # Aplicar filtro
        df_mostrar = h_df.copy()
        if filtro_tipo != "Todos":
            df_mostrar = h_df[h_df['tipo'] == filtro_tipo]

        # --- VISUALIZACIÓN ---
        st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
        
        # --- ACCIONES ---
        st.markdown(f"**Total de registros encontrados:** {len(df_mostrar)}")
        
        csv = df_mostrar.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 DESCARGAR AUDITORÍA (CSV)",
            data=csv,
            file_name=f"auditoria_movimientos_{datetime.now().strftime('%d_%m_%Y')}.csv",
            mime='text/csv',
        )
    else:
        st.info("No hay movimientos registrados para mostrar.")

st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
