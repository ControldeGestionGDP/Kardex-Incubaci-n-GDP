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

/* Animación de pollitos */
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

# --- FUNCIÓN PARA LLUVIA DE POLLITOS ---
def lluvia_de_pollitos():
    container = st.empty()
    pollitos_html = ""
    for i in range(25): # Un poco menos de pollitos para no saturar
        pos_x = i * 4
        delay = (i % 5) * 0.1 # Caída más rápida
        pollitos_html += f'<div class="pollito-anim" style="left:{pos_x}%; animation-delay:{delay}s;">🐣</div>'
    
    container.markdown(pollitos_html, unsafe_allow_html=True)
    time.sleep(1.2) # Reducir a la mitad el bloqueo del sistema
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
menu = ["Recepción", "Inventario Global", "Seguimiento & Decisiones", "Salidas (Incubación)", "Ficha de Trazabilidad", "Historial General"]
choice = st.sidebar.radio("Navegación:", menu)

# -------------------- RECEPCIÓN --------------------
if choice == "Recepción":
    t1, t2 = st.tabs(["Nuevo Ingreso", "Editar/Corregir"])
    with t1:
        st.header("Registro de Ingresos")
        with st.form("form_ingreso", clear_on_submit=True):
            col1, col2 = st.columns(2)
            lote_input = col1.text_input("Nro de Lote")
            planta = col2.selectbox("Planta Destino", ["P.I. Tarapoto", "P.I. Pucacaca", "P.I. Iquitos"])
            
            c_desc = st.selectbox("Descripción del Producto", ["HUEVO INCUBABLE PREMIUM", "HUEVO INCUBABLE NO PREMIUM"])
            
            c1, c2, c3 = st.columns(3)
            granja = c1.text_input("Granja")
            genetica = c2.selectbox("Genética", ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"])
            edad_repro = c3.number_input("Edad Repro", min_value=0)
            
            c4, c5, c6 = st.columns(3)
            cant_h = c4.number_input("Cantidad", min_value=0)
            f_postura = c5.date_input("Fecha Postura")
            f_llegada = c6.date_input("Fecha Llegada")
            
            obs = st.text_area("Notas Sanitarias")
            
            # --- BOTÓN DE GUARDAR ---
            if st.form_submit_button("GUARDAR REGISTRO"):
                if not lote_input:
                    st.error("El número de lote es obligatorio")
                else:
                    # 1. Generar ID y datos
                    id_u, proc = generar_id_y_procedencia(lote_input)
                    
                    # 2. Insertar en Google Sheets
                    insertar_lote([id_u, lote_input, proc, planta, granja, c_desc, genetica, edad_repro, str(f_postura), str(f_llegada), cant_h, cant_h, obs])
                    insertar_movimiento(["", id_u, planta, "INGRESO", cant_h, f"Recepción - {c_desc}", str(datetime.now())])
                    
                    # 3. Notificación Flotante (Toast) - SIN lluvia de pollitos
                    st.toast(f"Lote {id_u} registrado con éxito", icon="📥")
                    
                    # 4. Breve espera y refresco
                    time.sleep(1)
                    st.rerun()
    with t2:
        st.header("Editor de Lotes")
        df_lotes = cargar_lotes()
        
        lista_ids = ["Seleccionar..."] + df_lotes['id_unico'].dropna().tolist()
        id_edit = st.selectbox("Seleccione ID para modificar o eliminar:", lista_ids)
        
        if id_edit != "Seleccionar...":
            # Extraer datos y asegurar que no haya errores si faltan columnas
            datos = df_lotes[df_lotes["id_unico"]==id_edit].iloc[0]
            
            with st.form("f_edit"):
                col_e1, col_e2 = st.columns(2)
                
                # Descripción (Columna F)
                opciones_desc = ["HUEVO INCUBABLE PREMIUM", "HUEVO INCUBABLE NO PREMIUM"]
                val_desc = str(datos.get('descripcion', ''))
                idx_desc = opciones_desc.index(val_desc) if val_desc in opciones_desc else 0
                
                e_desc = col_e1.selectbox("Descripción", opciones_desc, index=idx_desc)
                
                # Planta (Columna D)
                opciones_planta = ["P.I. Tarapoto", "P.I. Pucacaca", "P.I. Iquitos"]
                val_planta = str(datos.get('planta', ''))
                idx_planta = opciones_planta.index(val_planta) if val_planta in opciones_planta else 0
                e_planta = col_e2.selectbox("Planta", opciones_planta, index=idx_planta)
                
                col_f1, col_f2 = st.columns(2)
                # Manejo seguro de fechas para evitar errores de casteo
                try:
                    f_post_val = pd.to_datetime(datos['fecha_postura']).date()
                except:
                    f_post_val = date.today()
                    
                try:
                    f_lleg_val = pd.to_datetime(datos['fecha_llegada']).date()
                except:
                    f_lleg_val = date.today()

                e_f_postura = col_f1.date_input("Fecha Postura", value=f_post_val)
                e_f_llegada = col_f2.date_input("Fecha Llegada", value=f_lleg_val)
                
                ce1, ce2, ce3 = st.columns(3)
                # Genética (Columna G)
                opciones_gen = ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"]
                val_gen = str(datos.get('linea_genetica', ''))
                idx_gen = opciones_gen.index(val_gen) if val_gen in opciones_gen else 3
                e_gen = ce1.selectbox("Genética", opciones_gen, index=idx_gen)
                
                # EDAD REPRO (Columna H) - Manejo de error si está vacío
                try:
                    val_edad = int(datos['edad_repro']) if datos['edad_repro'] != "" else 0
                except:
                    val_edad = 0
                e_edad = ce2.number_input("Edad Repro", value=val_edad)
                
                # SALDO (Columna L)
                try:
                    val_saldo = int(datos['saldo']) if datos['saldo'] != "" else 0
                except:
                    val_saldo = 0
                e_saldo = ce3.number_input("Saldo", value=val_saldo)
                
                e_obs = st.text_area("Observaciones", value=str(datos.get('obs_sanitarias', '')))
                
                # EL BOTÓN DE SUBMIT (Indispensable para que el form funcione)
                btn_update = st.form_submit_button("ACTUALIZAR DATOS")

                if btn_update:
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
                    
                    for col_name, val in update_dict.items():
                        if col_name in headers:
                            col_idx = headers.index(col_name) + 1
                            lotes_ws.update_cell(fila_idx, col_idx, str(val))
                    
                    st.toast(f"Lote {id_edit} actualizado", icon="🔃")
                    time.sleep(1)
                    st.rerun()

            # --- ELIMINACIÓN ---
            st.markdown("---")
            with st.expander("ZONA DE PELIGRO - Borrar Registro"):
                confirmar_check = st.checkbox(f"Confirmo que deseo borrar permanentemente el lote {id_edit}")
    
                if st.button("🗑️ ELIMINAR INGRESO AHORA"):
                    if confirmar_check:
                        df_actual = cargar_lotes()
                        filas = df_actual[df_actual['id_unico'] == id_edit].index
            
                        if not filas.empty:
                            fila_a_borrar = filas[0] + 2
                            lotes_ws.delete_rows(int(fila_a_borrar))
                
                            # --- NOTIFICACIÓN FLOTANTE ---
                            st.toast(f"Registro {id_edit} eliminado correctamente", icon="⚠️")
                
                            # Pausa para que el usuario note la desaparición antes del rerun
                            time.sleep(1.2)
                            st.rerun()
                    else:
                        # Si intenta borrar sin marcar el check, le avisamos con otro toast
                        st.toast("Debes marcar la casilla de confirmación primero", icon="🚫")

# -------------------- INVENTARIO --------------------
elif choice == "Inventario Global":
    st.header("Consolidado de Stock")
    
    # 1. Cargar datos base
    df = cargar_lotes()
    
    if not df.empty:
        # Filtrar solo lo que tiene stock
        df = df[df["saldo"] > 0].copy()
        df['Días Almacén'] = df['fecha_postura'].apply(calcular_dias)

        # --- BLOQUE DE FILTROS ---
        with st.container(border=True):
            st.subheader("Filtros de Búsqueda")
            col_f1, col_f2, col_f3 = st.columns(3)
            
            # Filtro por Planta
            lista_plantas = ["TODAS"] + sorted(df['planta'].unique().tolist())
            filtro_planta = col_f1.selectbox("Filtrar por Planta:", lista_plantas)
            
            # Filtro por Fecha de Llegada
            # Convertimos a datetime para asegurar la comparación
            df['fecha_llegada_dt'] = pd.to_datetime(df['fecha_llegada']).dt.date
            fechas_disponibles = sorted(df['fecha_llegada_dt'].unique())
            filtro_fecha = col_f2.selectbox("Fecha de Llegada:", ["TODAS"] + [str(f) for f in fechas_disponibles])
            
            # Filtro por Lote (Texto libre)
            filtro_lote = col_f3.text_input("Buscar Lote (Nro o ID):", placeholder="Escriba aquí...")

        # --- APLICACIÓN DE FILTROS ---
        df_filtrado = df.copy()

        if filtro_planta != "TODAS":
            df_filtrado = df_filtrado[df_filtrado['planta'] == filtro_planta]
            
        if filtro_fecha != "TODAS":
            df_filtrado = df_filtrado[df_filtrado['fecha_llegada_dt'].astype(str) == filtro_fecha]
            
        if filtro_lote:
            # Busca coincidencias parciales tanto en el Nro de Lote como en el ID Único
            df_filtrado = df_filtrado[
                df_filtrado['lote_nro'].astype(str).str.contains(filtro_lote, case=False) | 
                df_filtrado['id_unico'].str.contains(filtro_lote, case=False)
            ]

        # --- VISUALIZACIÓN ---
        # Quitamos la columna auxiliar de fecha para mostrar la tabla limpia
        df_display = df_filtrado.drop(columns=['fecha_llegada_dt'])
        
        st.write(f"Mostrando **{len(df_display)}** registros encontrados.")
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        # Botón de descarga para los datos filtrados
        st.download_button(
            label="DESCARGAR EXCEL FILTRADO",
            data=to_excel(df_display),
            file_name=f"Inventario_{filtro_planta}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        )
    else:
        st.info("No hay lotes con saldo disponible en este momento.")
# -------------------- SEGUIMIENTO Y DECISIONES --------------------
elif choice == "Seguimiento & Decisiones":
    st.header("Seguimiento y Clasificación")
    df = cargar_lotes()
    df = df[df["saldo"]>0]
    df['Días'] = df['fecha_postura'].apply(calcular_dias)
    df['Clasif. Repro'] = df['edad_repro'].apply(clasificar_repro)
    df = df.sort_values(by="Días", ascending=False)
    def color_semaforo(row):
        if row['Días'] > 10: return ['background-color: #ffcccc']*len(row)
        elif 7<=row['Días']<=9: return ['background-color: #fff4cc']*len(row)
        else: return ['background-color: #d4edda']*len(row)
    st.dataframe(df.style.apply(color_semaforo, axis=1), use_container_width=True)

# -------------------- SALIDAS --------------------
elif choice == "Salidas (Incubación)":
    st.header("Orden de Salida")
    df = cargar_lotes()
    df = df[df["saldo"] > 0]
    
    if not df.empty:
        # Contenedor principal para la orden
        with st.container(border=True):
            # Colocamos estos campos fuera de un form interno para que sean reactivos
            id_s = st.selectbox("Seleccione Lote", df["id_unico"])
            cant = st.number_input("Cantidad", min_value=1)
            mot = st.selectbox("Motivo", ["Carga Incubadora", "Traslado entre Plantas", "Venta", "Merma"])

            # --- LÓGICA DINÁMICA (AQUÍ ESTÁ EL TRUCO) ---
            detalle_adicional = ""
            
            if mot == "Carga Incubadora":
                nro_inc = st.text_input("N° de Incubadora", placeholder="Ej: INC-01")
                detalle_adicional = f"INCUBADORA: {nro_inc}"
                
            elif mot == "Traslado entre Plantas":
                p_dest = st.selectbox("Planta de Destino", ["P.I. Tarapoto", "P.I. Pucacaca", "P.I. Iquitos"])
                detalle_adicional = f"A PLANTA: {p_dest}"

            # Espacio visual
            st.markdown("---")
            
            # Botón de acción (Fuera de un st.form para evitar el lag de actualización)
            if st.button("PROCESAR SALIDA"):
                lote_info = df[df["id_unico"] == id_s].iloc[0]
                
                if cant <= lote_info['saldo']:
                    nuevo_saldo = int(lote_info['saldo'] - cant)
                    
                    # Definimos el texto final que irá a la columna 'motivo' en Sheets
                    motivo_final = f"{mot} ({detalle_adicional})" if detalle_adicional else mot
                    
                    # 1. Actualizar Saldo
                    actualizar_saldo(id_s, nuevo_saldo)
                    
                    # 2. Registrar Movimiento
                    insertar_movimiento([
                        "", 
                        id_s, 
                        lote_info["planta"], 
                        "SALIDA", 
                        cant, 
                        motivo_final.upper(), 
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ])
                    
                    st.success(f"Éxito: {motivo_final}")
                    lluvia_de_pollitos()
                    st.rerun()
                else:
                    st.error("No hay suficiente saldo para esta operación.")
    else:
        st.info("Inventario vacío.")
        
# -------------------- FICHA DE TRAZABILIDAD --------------------
elif choice == "Ficha de Trazabilidad":
    st.header("Expediente de Lote")
    df = cargar_lotes()
    target = st.selectbox("Buscar Lote:", ["Seleccionar..."] + df['id_unico'].tolist())
    if target != "Seleccionar...":
        info = df[df['id_unico']==target].iloc[0]
        movs = cargar_movimientos()
        movs = movs[movs['id_lote']==target].sort_values(by="fecha", ascending=False)
        st.subheader("Estado en Tiempo Real")
        m1,m2,m3,m4 = st.columns(4)
        with m1: st.markdown(f'<div class="info-card"><div class="info-label">Saldo en Cámara</div><div class="info-value">{info["saldo"]} Huevos</div></div>', unsafe_allow_html=True)
        with m2: st.markdown(f'<div class="info-card"><div class="info-label">Tipo de Huevo</div><div class="info-value">{info.get("descripcion", "N/A")}</div></div>', unsafe_allow_html=True)
        with m3: st.markdown(f'<div class="info-card"><div class="info-label">Días de Almacén</div><div class="info-value">{calcular_dias(info["fecha_postura"])} Días</div></div>', unsafe_allow_html=True)
        with m4: st.markdown(f'<div class="info-card"><div class="info-label">Edad Repro</div><div class="info-value">{info["edad_repro"] if info["edad_repro"] else "S/D"} Sem.</div></div>', unsafe_allow_html=True)
        st.subheader("Datos Técnicos de Producción")
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.markdown(f'<div class="info-card"><div class="info-label">Granja</div><div class="info-value">{info["granja"]}</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="info-card"><div class="info-label">Línea Genética</div><div class="info-value">{info["linea_genetica"]}</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="info-card"><div class="info-label">Procedencia</div><div class="info-value">{info["procedencia"]}</div></div>', unsafe_allow_html=True)
        with c4: st.markdown(f'<div class="info-card"><div class="info-label">Lote Externo</div><div class="info-value">{info["lote_nro"]}</div></div>', unsafe_allow_html=True)
        st.warning(f" **Observaciones Sanitarias:** {info['obs_sanitarias']}")
        st.divider()
        col_t1,col_t2 = st.columns([3,1])
        col_t1.subheader("Movimientos Registrados")
        if col_t2.download_button("EXPORTAR EXPEDIENTE", to_excel(movs), f"Expediente_{target}.xlsx"):
            st.toast(f"Reporte de {target} descargado")
        st.dataframe(movs, use_container_width=True)

# -------------------- HISTORIAL GENERAL --------------------
elif choice == "Historial General":
    st.header("Auditoría de Movimientos")
    h_df = cargar_movimientos()
    if not h_df.empty:
        st.dataframe(h_df, use_container_width=True)
        st.download_button("DESCARGAR AUDITORÍA", to_excel(h_df), "Auditoria.xlsx")

st.markdown('<div class="footer">Desarrollado por Gerencia de Control de Gestión</div>', unsafe_allow_html=True)
