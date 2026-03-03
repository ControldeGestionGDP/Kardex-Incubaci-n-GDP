import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials

# =====================================
# CONEXIÓN GOOGLE SHEETS
# =====================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=scope
)

client = gspread.authorize(creds)

SPREADSHEET_ID = "13nw5vYfEFnP3RjHXK7CC7124-MDKCe-iAwfycvTUeS0"

sheet = client.open_by_key(SPREADSHEET_ID)

lotes_ws = sheet.worksheet("lotes")
movimientos_ws = sheet.worksheet("movimientos")

# =====================================
# FUNCIONES
# =====================================

def cargar_lotes():
    data = lotes_ws.get_all_records()
    return pd.DataFrame(data)

def cargar_movimientos():
    data = movimientos_ws.get_all_records()
    return pd.DataFrame(data)

def insertar_lote(data):
    lotes_ws.append_row(data)

def insertar_movimiento(data):
    movimientos_ws.append_row(data)

def actualizar_saldo(id_unico, nuevo_saldo):
    df = cargar_lotes()
    fila = df[df["id_unico"] == id_unico].index
    if len(fila) > 0:
        row_number = fila[0] + 2
        lotes_ws.update_cell(row_number, 11, nuevo_saldo)

# =====================================
# INTERFAZ
# =====================================

st.title("IncubaTrack ERP")

menu = st.sidebar.selectbox(
    "Menú",
    ["Registrar Lote", "Ver Inventario", "Registrar Movimiento"]
)

# =====================================
# REGISTRAR LOTE
# =====================================

if menu == "Registrar Lote":

    st.subheader("Nuevo Lote")

    lote_nro = st.text_input("Número de Lote")
    procedencia = st.text_input("Procedencia")
    planta = st.text_input("Planta")
    granja = st.text_input("Granja")
    linea = st.text_input("Línea Genética")
    edad = st.number_input("Edad Reproductiva", min_value=0)
    fecha_postura = st.date_input("Fecha Postura")
    fecha_llegada = st.date_input("Fecha Llegada")
    cantidad = st.number_input("Cantidad Inicial", min_value=0)
    obs = st.text_area("Observaciones")

    if st.button("Guardar Lote"):

        id_unico = "L-" + datetime.now().strftime("%Y%m%d%H%M%S")

        nuevo_lote = [
            id_unico,
            lote_nro,
            procedencia,
            planta,
            granja,
            linea,
            edad,
            str(fecha_postura),
            str(fecha_llegada),
            cantidad,
            cantidad,
            obs
        ]

        insertar_lote(nuevo_lote)

        nuevo_mov = [
            "",
            id_unico,
            planta,
            "INGRESO",
            cantidad,
            "Recepción",
            str(datetime.now())
        ]

        insertar_movimiento(nuevo_mov)

        st.success("Lote guardado correctamente")

# =====================================
# VER INVENTARIO
# =====================================

elif menu == "Ver Inventario":

    st.subheader("Inventario Actual")

    df = cargar_lotes()

    if df.empty:
        st.warning("No hay lotes registrados")
    else:
        st.dataframe(df)

# =====================================
# REGISTRAR MOVIMIENTO
# =====================================

elif menu == "Registrar Movimiento":

    st.subheader("Salida / Ajuste")

    df = cargar_lotes()

    if df.empty:
        st.warning("No hay lotes disponibles")
    else:

        id_unico = st.selectbox("Seleccionar Lote", df["id_unico"])

        tipo = st.selectbox("Tipo", ["SALIDA", "AJUSTE"])

        cantidad = st.number_input("Cantidad", min_value=1)

        motivo = st.text_input("Motivo")

        if st.button("Registrar Movimiento"):

            lote = df[df["id_unico"] == id_unico].iloc[0]
            saldo_actual = lote["saldo"]
            nuevo_saldo = saldo_actual - cantidad

            if nuevo_saldo < 0:
                st.error("Saldo insuficiente")
            else:

                actualizar_saldo(id_unico, nuevo_saldo)

                nuevo_mov = [
                    "",
                    id_unico,
                    lote["planta"],
                    tipo,
                    cantidad,
                    motivo,
                    str(datetime.now())
                ]

                insertar_movimiento(nuevo_mov)

                st.success("Movimiento registrado")
