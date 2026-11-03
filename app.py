"""IncubaTrack 2.0 | Trazabilidad de huevo incubable entre plantas.

Requisitos: streamlit, pandas, gspread, google-auth, xlsxwriter.
Conserva intactas las hojas originales «lotes» y «movimientos».
Escritura exclusiva en: traz_lotes_v2, traz_eventos_v2,
traz_traslados_v2 y traz_recepciones_v2.

IMPORTANTE: Google Sheets no garantiza transacciones multihoja ni bloqueos
entre usuarios. La app usa operaciones idempotentes y un panel de incidencias,
pero para múltiples operadores concurrentes se recomienda PostgreSQL.
"""
from __future__ import annotations

from datetime import date, datetime, time as dt_time
from html import escape
from io import BytesIO
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


# ─────────────────────────────── CONFIGURACIÓN ────────────────────────────────
st.set_page_config(page_title="IncubaTrack 2.0 · Trazabilidad", page_icon="🥚", layout="wide", initial_sidebar_state="expanded")
TZ = ZoneInfo("America/Lima")
PLANTAS = ["P.I. Tarapoto", "P.I. Pucacaca", "P.I. Iquitos"]
DESCRIPCIONES = ["HUEVO INCUBABLE PREMIUM", "HUEVO INCUBABLE NO PREMIUM"]
GENETICAS = ["Cobb 500", "Ross 308", "Hubbard", "Sin Datos"]
ID_PLANILLA_DEFAULT = "13nw5vYfEFnP3RjHXK7CC7124-MDKCe-iAwfycvTUeS0"
HOJAS = {
    "traz_lotes_v2": [
        "id_lote", "id_raiz", "id_padre", "lote_nro", "procedencia", "planta",
        "granja", "descripcion", "genetica", "edad_repro", "fecha_postura",
        "fecha_llegada", "cantidad_origen", "obs_sanitarias", "origen_registro", "fecha_creacion", "creado_por",
    ],
    "traz_eventos_v2": [
        "id_evento", "id_lote", "id_raiz", "tipo", "cantidad", "variacion",
        "planta", "planta_contraparte", "id_traslado", "referencia",
        "fecha_evento", "responsable", "observaciones", "metadata_json",
    ],
    "traz_traslados_v2": [
        "id_traslado", "id_lote_origen", "id_lote_destino", "id_raiz", "lote_nro",
        "planta_origen", "planta_destino", "cantidad_enviada", "fecha_envio",
        "guia", "transportista", "placa", "logtag", "temperatura_salida",
        "observaciones", "responsable", "creado_en",
    ],
    "traz_recepciones_v2": [
        "id_recepcion", "id_traslado", "id_lote_destino", "fecha_recepcion",
        "cantidad_aceptada", "cantidad_rechazada", "cantidad_faltante",
        "temperatura_llegada", "condicion", "observaciones", "responsable", "creado_en",
    ],
}

st.markdown("""
<style>
[data-testid="stAppViewContainer"] {background:#f7f9fc;}
.block-container {padding-top:1.25rem; padding-bottom:3.5rem;max-width:1500px;}
[data-testid="stSidebar"] {background:#ffffff; border-right:1px solid #e5eaf1;}
[data-testid="stSidebar"] * {color:#253447;}
h1,h2,h3 {color:#183b5b; letter-spacing:-.025em;}
h1 {font-size:1.85rem !important;}
[data-testid="stMetric"] {background:#fff;border:1px solid #e6ebf2;border-radius:12px;
 padding:14px 17px;box-shadow:0 2px 8px rgba(19,54,93,.035);}
[data-testid="stMetricLabel"]{color:#697a8d;}
[data-testid="stMetricValue"] {color:#163f60;}
div[data-testid="stVerticalBlockBorderWrapper"] > div {border-color:#e6ebf2;}
.stButton > button[kind="primary"] {background:#0b628c;border-color:#0b628c;}
.stButton > button {border-radius:9px;}
.section-intro {font-size:.9rem;color:#65778a;margin:-7px 0 18px;}
.smallnote {color:#6a7b8c;font-size:.78rem;}
.kicker {color:#0b628c;font-weight:700;font-size:.72rem;letter-spacing:.10em;text-transform:uppercase;}
hr {border-color:#e7ebf1;}
</style>
""", unsafe_allow_html=True)


def ahora() -> datetime:
    return datetime.now(TZ)


def sello() -> str:
    return ahora().isoformat(timespec="seconds")


def fecha_iso(valor) -> str:
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip()


def momento(fecha: date, hora: dt_time) -> str:
    return datetime.combine(fecha, hora, TZ).isoformat(timespec="seconds")


def entero(valor, predeterminado=0) -> int:
    try:
        if valor is None or str(valor).strip() == "":
            return predeterminado
        return int(round(float(str(valor).replace(",", ""))))
    except (TypeError, ValueError):
        return predeterminado


def seguro(valor) -> str:
    return escape(str(valor if valor is not None else ""))


def dias_desde(fecha, hoy=None):
    d = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(d):
        return None
    return ((hoy or ahora().date()) - d.date()).days


def id_nuevo(prefijo: str) -> str:
    return f"{prefijo}-{ahora():%y%m%d}-{uuid4().hex[:10].upper()}"


def clave_borrador(nombre: str, prefijo: str):
    clave = f"borrador_{nombre}"
    if clave not in st.session_state:
        st.session_state[clave] = id_nuevo(prefijo)
    return st.session_state[clave]


def nuevo_borrador(nombre: str, prefijo: str):
    st.session_state[f"borrador_{nombre}"] = id_nuevo(prefijo)


def exito_y_recargar(texto: str):
    st.session_state["mensaje_exito"] = texto
    cargar_tabla.clear()
    st.rerun()


def normalizar_procedencia(lote: str) -> str:
    t = lote.upper().strip()
    if t.isdigit():
        return "CDG"
    if "SF" in t:
        return "San Fernando"
    if "SE" in t:
        return "Santa Elena"
    return "Otros"


def excel_hojas(datos: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for nombre, df in datos.items():
            nombre_hoja = nombre[:31]
            df.to_excel(writer, sheet_name=nombre_hoja, index=False)
            hoja = writer.sheets[nombre_hoja]
            hoja.freeze_panes(1, 0)
            hoja.set_row(0, 23, writer.book.add_format({"bold": True, "bg_color": "#153e5c", "font_color": "#ffffff"}))
            for j, col in enumerate(df.columns):
                hoja.set_column(j, j, min(max(len(str(col)) + 3, 14), 36))
    return buffer.getvalue()


# ─────────────────────────────── PERSISTENCIA ────────────────────────────────
@st.cache_resource(show_spinner=False)
def conectar():
    credenciales = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    cliente = gspread.authorize(credenciales)
    archivo = cliente.open_by_key(st.secrets.get("SPREADSHEET_ID", ID_PLANILLA_DEFAULT))
    return archivo


def hoja(nombre: str):
    return conectar().worksheet(nombre)


def preparar_hojas():
    libro = conectar()
    existentes = {ws.title: ws for ws in libro.worksheets()}
    for nombre, columnas in HOJAS.items():
        if nombre not in existentes:
            try:
                ws = libro.add_worksheet(title=nombre, rows=2000, cols=len(columnas))
                ws.append_row(columnas, value_input_option="RAW")
            except gspread.exceptions.APIError:
                # Otro operador pudo haber creado la hoja al mismo tiempo.
                ws = libro.worksheet(nombre)
        else:
            ws = existentes[nombre]
        encabezado = ws.row_values(1)
        if encabezado != columnas:
            raise ValueError(
                f"La hoja {nombre} tiene encabezados distintos a los esperados. "
                "No se modifica automáticamente para proteger tus datos."
            )


@st.cache_data(ttl=25, show_spinner=False)
def cargar_tabla(nombre: str) -> pd.DataFrame:
    df = pd.DataFrame(hoja(nombre).get_all_records(default_blank=""))
    if nombre in HOJAS:
        return df.reindex(columns=HOJAS[nombre]).fillna("")
    return df.fillna("")


def append_registro(nombre: str, registro: dict):
    hoja(nombre).append_row([registro.get(c, "") for c in HOJAS[nombre]], value_input_option="RAW")
    cargar_tabla.clear()


def append_varios(nombre: str, registros: list[dict], tam_lote: int = 150):
    for inicio in range(0, len(registros), tam_lote):
        grupo = registros[inicio: inicio + tam_lote]
        hoja(nombre).append_rows(
            [[r.get(col, "") for col in HOJAS[nombre]] for r in grupo],
            value_input_option="RAW",
        )
        cargar_tabla.clear()


def tabla_fresca(nombre: str) -> pd.DataFrame:
    # Durante la escritura NO usar el caché para validar cantidades y duplicados.
    df = pd.DataFrame(hoja(nombre).get_all_records(default_blank=""))
    return df.reindex(columns=HOJAS[nombre]).fillna("")


def existe(df: pd.DataFrame, columna: str, valor: str) -> bool:
    return not df.empty and df[columna].astype(str).eq(str(valor)).any()


def registrar_evento(
    id_evento: str, id_lote: str, id_raiz: str, tipo: str, cantidad: int,
    variacion: int, planta: str, responsable: str, observaciones="",
    planta_contraparte="", id_traslado="", referencia="", fecha_evento=None,
    metadata=None,
):
    if existe(tabla_fresca("traz_eventos_v2"), "id_evento", id_evento):
        return False
    append_registro("traz_eventos_v2", {
        "id_evento": id_evento, "id_lote": id_lote, "id_raiz": id_raiz,
        "tipo": tipo, "cantidad": int(cantidad), "variacion": int(variacion),
        "planta": planta, "planta_contraparte": planta_contraparte,
        "id_traslado": id_traslado, "referencia": referencia,
        "fecha_evento": fecha_evento or sello(), "responsable": responsable,
        "observaciones": observaciones,
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False, default=str),
    })
    return True


# ─────────────────────────────── MODELO DE DATOS ─────────────────────────────
def preparar_estado(lotes=None, eventos=None, traslados=None, recepciones=None):
    l = cargar_tabla("traz_lotes_v2") if lotes is None else lotes.copy()
    e = cargar_tabla("traz_eventos_v2") if eventos is None else eventos.copy()
    t = cargar_tabla("traz_traslados_v2") if traslados is None else traslados.copy()
    r = cargar_tabla("traz_recepciones_v2") if recepciones is None else recepciones.copy()

    for col in ("cantidad", "variacion"):
        e[col] = pd.to_numeric(e[col], errors="coerce").fillna(0).astype(int)
    for col in ("cantidad_enviada",):
        t[col] = pd.to_numeric(t[col], errors="coerce").fillna(0).astype(int)
    for col in ("cantidad_aceptada", "cantidad_rechazada", "cantidad_faltante"):
        r[col] = pd.to_numeric(r[col], errors="coerce").fillna(0).astype(int)
    l["edad_repro"] = pd.to_numeric(l["edad_repro"], errors="coerce").fillna(0).astype(int)

    saldo = e.groupby("id_lote", dropna=False)["variacion"].sum()
    l["saldo"] = l["id_lote"].map(saldo).fillna(0).astype(int)
    l["dias_postura"] = l["fecha_postura"].apply(dias_desde)
    l["dias_planta"] = l["fecha_llegada"].apply(dias_desde)

    if not t.empty:
        totales = r.groupby("id_traslado")[["cantidad_aceptada", "cantidad_rechazada", "cantidad_faltante"]].sum()
        for campo in totales.columns:
            t[campo] = t["id_traslado"].map(totales[campo]).fillna(0).astype(int)
        t["pendiente"] = (t["cantidad_enviada"] - t["cantidad_aceptada"] - t["cantidad_rechazada"] - t["cantidad_faltante"]).astype(int)
        salidas = set(e.loc[e["tipo"] == "TRASLADO_ENVIO", "id_traslado"].astype(str))
        t["estado"] = t.apply(
            lambda x: "SIN DESPACHO" if str(x["id_traslado"]) not in salidas else
            "ERROR: EXCESO" if x["pendiente"] < 0 else
            "EN TRANSITO" if x["pendiente"] == x["cantidad_enviada"] else
            "RECIBIDO CON DIFERENCIAS" if x["pendiente"] == 0 and (x["cantidad_rechazada"] + x["cantidad_faltante"]) > 0 else
            "RECIBIDO" if x["pendiente"] == 0 else "RECEPCION PARCIAL",
            axis=1,
        )
    else:
        for campo in ("cantidad_aceptada", "cantidad_rechazada", "cantidad_faltante", "pendiente", "estado"):
            t[campo] = pd.Series(dtype="object" if campo == "estado" else "int64")
    return l, e, t, r


def stock_fresco(id_lote: str) -> int:
    e = tabla_fresca("traz_eventos_v2")
    if e.empty:
        return 0
    ev = e[e["id_lote"].astype(str) == str(id_lote)]
    return int(pd.to_numeric(ev["variacion"], errors="coerce").fillna(0).sum())


def resumen_traslado_fresco(id_traslado: str):
    _, e, t, r = preparar_estado(
        tabla_fresca("traz_lotes_v2"), tabla_fresca("traz_eventos_v2"),
        tabla_fresca("traz_traslados_v2"), tabla_fresca("traz_recepciones_v2"),
    )
    x = t[t["id_traslado"].astype(str) == id_traslado]
    if x.empty:
        return None, e, r
    return x.iloc[0], e, r


def validar_responsable(responsable: str) -> str:
    responsable = responsable.strip()
    if len(responsable) < 3:
        raise ValueError("Escribe el nombre del responsable (mínimo 3 caracteres).")
    return responsable


def guardar_ingreso(datos: dict, responsable: str):
    responsable = validar_responsable(responsable)
    if not datos["lote_nro"].strip():
        raise ValueError("El número del lote es obligatorio.")
    if datos["cantidad"] <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    if datos["fecha_postura"] > datos["fecha_llegada"]:
        raise ValueError("La fecha de postura no puede superar la fecha de llegada.")
    if datos["fecha_llegada"] > ahora().date():
        raise ValueError("La fecha de llegada no puede ser futura.")

    id_lote = datos["id_lote"]
    lotes = tabla_fresca("traz_lotes_v2")
    if not existe(lotes, "id_lote", id_lote):
        append_registro("traz_lotes_v2", {
            "id_lote": id_lote, "id_raiz": id_lote, "id_padre": "",
            "lote_nro": datos["lote_nro"].strip().upper(),
            "procedencia": datos["procedencia"], "planta": datos["planta"],
            "granja": datos["granja"].strip(), "descripcion": datos["descripcion"],
            "genetica": datos["genetica"], "edad_repro": datos["edad_repro"],
            "fecha_postura": fecha_iso(datos["fecha_postura"]),
            "fecha_llegada": fecha_iso(datos["fecha_llegada"]),
            "cantidad_origen": datos["cantidad"],
            "obs_sanitarias": datos["observaciones"], "origen_registro": "RECEPCION_EXTERNA",
            "fecha_creacion": sello(), "creado_por": responsable,
        })
    else:
        registrado = lotes[lotes["id_lote"].astype(str) == id_lote].iloc[0]
        if entero(registrado["cantidad_origen"]) != datos["cantidad"] or str(registrado["planta"]) != datos["planta"]:
            raise ValueError("Existe un borrador previo con diferente cantidad/planta. Verifica el registro antes de reintentar.")
    registrar_evento(
        "ING-" + id_lote, id_lote, id_lote, "RECEPCION_EXTERNA",
        datos["cantidad"], datos["cantidad"], datos["planta"], responsable,
        datos["observaciones"], referencia="RECEPCION EXTERNA",
        fecha_evento=momento(datos["fecha_llegada"], datos["hora_llegada"]),
    )


def guardar_traslado(datos: dict, responsable: str):
    responsable = validar_responsable(responsable)
    if datos["planta_origen"] == datos["planta_destino"]:
        raise ValueError("La planta de destino debe ser distinta de la de origen.")
    if datos["cantidad_enviada"] <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    if datos["fecha_salida"] > ahora().date():
        raise ValueError("La fecha de salida no puede ser futura.")
    existente = tabla_fresca("traz_traslados_v2")
    if not existe(existente, "id_traslado", datos["id_traslado"]):
        l = tabla_fresca("traz_lotes_v2")
        x = l[l["id_lote"].astype(str) == datos["id_lote_origen"]]
        if x.empty:
            raise ValueError("El lote no existe; actualiza los datos.")
        x = x.iloc[0]
        if x["planta"] != datos["planta_origen"]:
            raise ValueError("La planta de origen no corresponde al lote.")
        if datos["cantidad_enviada"] > stock_fresco(datos["id_lote_origen"]):
            raise ValueError("Stock insuficiente. Otro movimiento pudo haber consumido el saldo.")
        append_registro("traz_traslados_v2", {
            "id_traslado": datos["id_traslado"], "id_lote_origen": datos["id_lote_origen"],
            "id_lote_destino": datos["id_lote_destino"], "id_raiz": x["id_raiz"],
            "lote_nro": x["lote_nro"], "planta_origen": datos["planta_origen"],
            "planta_destino": datos["planta_destino"], "cantidad_enviada": datos["cantidad_enviada"],
            "fecha_envio": momento(datos["fecha_salida"], datos["hora_salida"]),
            "guia": datos["guia"], "transportista": datos["transportista"],
            "placa": datos["placa"], "logtag": datos["logtag"],
            "temperatura_salida": datos["temperatura_salida"],
            "observaciones": datos["observaciones"], "responsable": responsable, "creado_en": sello(),
        })
    # Reintentos: escribir el despacho usando exactamente el documento persistido.
    # Así no se descuentan cantidades diferentes por cambios en el formulario.
    documento = tabla_fresca("traz_traslados_v2")
    original = documento[documento["id_traslado"].astype(str) == datos["id_traslado"]].iloc[0]
    if (str(original["id_lote_origen"]) != datos["id_lote_origen"] or
            entero(original["cantidad_enviada"]) != datos["cantidad_enviada"] or
            str(original["planta_destino"]) != datos["planta_destino"]):
        raise ValueError("Este ID de traslado ya existe con otros datos. Revisar Auditoría.")
    registrar_evento(
        "ENV-" + datos["id_traslado"], str(original["id_lote_origen"]), str(original["id_raiz"]),
        "TRASLADO_ENVIO", entero(original["cantidad_enviada"]), -entero(original["cantidad_enviada"]),
        str(original["planta_origen"]), responsable, str(original["observaciones"]),
        planta_contraparte=str(original["planta_destino"]), id_traslado=datos["id_traslado"],
        referencia=str(original["guia"]), fecha_evento=str(original["fecha_envio"]),
    )


def guardar_recepcion_traslado(datos: dict, responsable: str):
    responsable = validar_responsable(responsable)
    tra, eventos, r = resumen_traslado_fresco(datos["id_traslado"])
    if tra is None:
        raise ValueError("No se encontró el traslado solicitado.")
    # Reintentar una confirmación ya finalizada nunca debe descontar el pendiente.
    if existe(r, "id_recepcion", datos["id_recepcion"]):
        return False
    if not existe(eventos[eventos["tipo"] == "TRASLADO_ENVIO"], "id_traslado", datos["id_traslado"]):
        raise ValueError("Este envío carece de movimiento de despacho. Revisar Auditoría.")
    if datos["fecha_recepcion"] > ahora().date():
        raise ValueError("La recepción no puede registrarse con una fecha futura.")
    if momento(datos["fecha_recepcion"], datos["hora_recepcion"]) < str(tra["fecha_envio"]):
        raise ValueError("La fecha y hora de recepción no pueden preceder al despacho.")
    if min(datos["aceptada"], datos["rechazada"], datos["faltante"]) < 0:
        raise ValueError("Ninguna cantidad puede ser negativa.")
    cantidad_total = datos["aceptada"] + datos["rechazada"] + datos["faltante"]
    if cantidad_total <= 0:
        raise ValueError("Debes registrar al menos un huevo recibido, rechazado o faltante.")
    if cantidad_total > entero(tra["pendiente"]):
        raise ValueError("La suma supera la cantidad pendiente de recepción.")
    if datos["rechazada"] + datos["faltante"] > 0 and not datos["observaciones"].strip():
        raise ValueError("Las diferencias deben tener una explicación en observaciones.")
    # Bloquear nuevas recepciones si hay un evento anterior sin confirmación.
    confirmadas = set(r["id_recepcion"].astype(str))
    pendientes_de_recuperar = eventos[
        (eventos["tipo"] == "RECEPCION_TRASLADO") &
        (eventos["id_traslado"].astype(str) == datos["id_traslado"]) &
        (~eventos["referencia"].astype(str).isin(confirmadas))
    ]
    no_reparados = pendientes_de_recuperar[
        pendientes_de_recuperar["referencia"].astype(str) != datos["id_recepcion"]
    ]
    if not no_reparados.empty:
        raise ValueError("Hay una recepción incompleta de este traslado. Repara esa operación antes de registrar otra.")
    if not pendientes_de_recuperar.empty:
        anterior = pendientes_de_recuperar.iloc[0]
        if entero(anterior["cantidad"]) != datos["aceptada"]:
            raise ValueError("Este borrador fue grabado parcialmente con otra cantidad aceptada. Conserva los datos originales.")

    if datos["aceptada"] > 0:
        lotes = tabla_fresca("traz_lotes_v2")
        if not existe(lotes, "id_lote", tra["id_lote_destino"]):
            padres = lotes[lotes["id_lote"].astype(str) == str(tra["id_lote_origen"])]
            if padres.empty:
                raise ValueError("Falta el lote de origen; no se puede reconstruir la trazabilidad.")
            p = padres.iloc[0]
            append_registro("traz_lotes_v2", {
                "id_lote": tra["id_lote_destino"], "id_raiz": tra["id_raiz"],
                "id_padre": tra["id_lote_origen"], "lote_nro": p["lote_nro"],
                "procedencia": p["procedencia"], "planta": tra["planta_destino"],
                "granja": p["granja"], "descripcion": p["descripcion"],
                "genetica": p["genetica"], "edad_repro": p["edad_repro"],
                "fecha_postura": p["fecha_postura"], "fecha_llegada": fecha_iso(datos["fecha_recepcion"]),
                "cantidad_origen": 0,
                "obs_sanitarias": p["obs_sanitarias"], "origen_registro": "RECEPCION_TRASLADO",
                "fecha_creacion": sello(), "creado_por": responsable,
            })
    # Se guarda evento ANTES de la confirmación. Si falla Sheets, se puede
    # reintentar el mismo borrador sin duplicar el evento.
    registrar_evento(
        "RET-" + datos["id_recepcion"], tra["id_lote_destino"], tra["id_raiz"],
        "RECEPCION_TRASLADO", datos["aceptada"], datos["aceptada"],
        tra["planta_destino"], responsable, datos["observaciones"],
        planta_contraparte=tra["planta_origen"], id_traslado=datos["id_traslado"],
        referencia=datos["id_recepcion"],
        fecha_evento=momento(datos["fecha_recepcion"], datos["hora_recepcion"]),
        metadata={"fecha_recepcion": fecha_iso(datos["fecha_recepcion"]),
                  "hora_recepcion": str(datos["hora_recepcion"]),
                  "aceptada": datos["aceptada"], "rechazada": datos["rechazada"],
                  "faltante": datos["faltante"], "temperatura_llegada": datos["temperatura_llegada"],
                  "condicion": datos["condicion"], "observaciones": datos["observaciones"]},
    )
    append_registro("traz_recepciones_v2", {
        "id_recepcion": datos["id_recepcion"], "id_traslado": datos["id_traslado"],
        "id_lote_destino": tra["id_lote_destino"],
        "fecha_recepcion": momento(datos["fecha_recepcion"], datos["hora_recepcion"]),
        "cantidad_aceptada": datos["aceptada"],
        "cantidad_rechazada": datos["rechazada"], "cantidad_faltante": datos["faltante"],
        "temperatura_llegada": datos["temperatura_llegada"], "condicion": datos["condicion"],
        "observaciones": datos["observaciones"], "responsable": responsable, "creado_en": sello(),
    })
    return True


def guardar_salida(datos: dict, responsable: str):
    responsable = validar_responsable(responsable)
    if datos["cantidad"] <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    if datos["tipo"] == "SALIDA_INCUBADORA" and not datos["referencia"].strip():
        raise ValueError("Indica la incubadora o la carga correspondiente.")
    if datos["tipo"] in {"MERMA", "AJUSTE_POSITIVO", "AJUSTE_NEGATIVO"} and not datos["observaciones"].strip():
        raise ValueError("Es obligatorio justificar mermas y ajustes.")
    ev = tabla_fresca("traz_eventos_v2")
    if existe(ev, "id_evento", datos["id_evento"]):
        return False
    lotes = tabla_fresca("traz_lotes_v2")
    x = lotes[lotes["id_lote"].astype(str) == datos["id_lote"]]
    if x.empty:
        raise ValueError("El lote no existe.")
    x = x.iloc[0]
    signo = 1 if datos["tipo"] == "AJUSTE_POSITIVO" else -1
    if signo == -1 and stock_fresco(datos["id_lote"]) < datos["cantidad"]:
        raise ValueError("Cantidad superior al saldo disponible.")
    return registrar_evento(
        datos["id_evento"], datos["id_lote"], x["id_raiz"], datos["tipo"],
        datos["cantidad"], signo * datos["cantidad"], x["planta"], responsable,
        datos["observaciones"], referencia=datos["referencia"],
    )


def diagnosticos(lotes: pd.DataFrame, eventos: pd.DataFrame, traslados: pd.DataFrame, recepciones: pd.DataFrame) -> pd.DataFrame:
    problemas = []

    def agregar(tipo, referencia, detalle):
        problemas.append({"Control": tipo, "Referencia": referencia, "Detalle": detalle})

    for _, x in lotes[lotes["saldo"] < 0].iterrows():
        agregar("SALDO NEGATIVO", x["id_lote"], f"Saldo: {x['saldo']}")
    for nombre, df, clave in [
        ("lotes", lotes, "id_lote"), ("eventos", eventos, "id_evento"),
        ("traslados", traslados, "id_traslado"), ("recepciones", recepciones, "id_recepcion"),
    ]:
        for value in df.loc[df[clave].astype(str).duplicated(keep=False), clave].astype(str).unique():
            agregar("ID DUPLICADO", value, f"Duplicado en {nombre}")
    ids_lote = set(lotes["id_lote"].astype(str))
    ids_tra = set(traslados["id_traslado"].astype(str))
    for _, x in eventos.iterrows():
        if str(x["id_lote"]) not in ids_lote and (x["tipo"] != "RECEPCION_TRASLADO" or entero(x["cantidad"]) > 0):
            agregar("EVENTO SIN LOTE", x["id_evento"], x["id_lote"])
        if x["tipo"] in ("TRASLADO_ENVIO", "RECEPCION_TRASLADO") and str(x["id_traslado"]) not in ids_tra:
            agregar("EVENTO SIN TRASLADO", x["id_evento"], x["id_traslado"])
    for _, x in traslados.iterrows():
        if x["estado"] == "SIN DESPACHO":
            agregar("ENVIO INCOMPLETO", x["id_traslado"], "Existe documento sin evento de salida")
        if x["pendiente"] < 0:
            agregar("RECEPCION EXCEDIDA", x["id_traslado"], "Se recibió más de lo enviado")
        eventos_env = eventos[(eventos["tipo"] == "TRASLADO_ENVIO") & (eventos["id_traslado"].astype(str) == str(x["id_traslado"]))]
        if not eventos_env.empty and int(eventos_env["cantidad"].sum()) != int(x["cantidad_enviada"]):
            agregar("DESPACHO INCONSISTENTE", x["id_traslado"], "El documento difiere del movimiento")
    eventos_por_id = eventos.set_index("id_evento") if not eventos.empty else pd.DataFrame()
    for _, x in recepciones.iterrows():
        llave = "RET-" + str(x["id_recepcion"])
        if llave not in set(eventos["id_evento"].astype(str)):
            agregar("RECEPCION SIN EVENTO", x["id_recepcion"], "No consta movimiento de entrada")
        elif entero(eventos_por_id.loc[llave, "cantidad"]) != entero(x["cantidad_aceptada"]):
            agregar("CANTIDAD DE RECEPCION INCONSISTENTE", x["id_recepcion"], "Evento y confirmación difieren")
    ids_eventos = set(eventos["id_evento"].astype(str))
    for _, x in lotes.iterrows():
        origen = str(x["origen_registro"])
        llave = ("ING-" if origen == "RECEPCION_EXTERNA" else "LEG-") + str(x["id_lote"])
        if origen in {"RECEPCION_EXTERNA", "IMPORTADO_LEGACY"} and entero(x["cantidad_origen"]) > 0 and llave not in ids_eventos:
            agregar("LOTE SIN SALDO INICIAL", x["id_lote"], "Falta el evento de apertura/ingreso")
    recep_ids = set(recepciones["id_recepcion"].astype(str))
    for _, x in eventos[eventos["tipo"] == "RECEPCION_TRASLADO"].iterrows():
        referencia = str(x["referencia"])
        if referencia not in recep_ids:
            agregar("EVENTO SIN CONFIRMACION", x["id_evento"], "Recepción pendiente de completar")
    return pd.DataFrame(problemas, columns=["Control", "Referencia", "Detalle"])


def migrar_desde_legacy(responsable: str):
    responsable = validar_responsable(responsable)
    origen = pd.DataFrame(hoja("lotes").get_all_records(default_blank=""))
    requeridas = {"id_unico", "lote_nro", "planta", "saldo", "fecha_postura", "fecha_llegada"}
    if not requeridas.issubset(origen.columns):
        raise ValueError(f"Faltan columnas en hoja histórica 'lotes': {sorted(requeridas-set(origen.columns))}")
    ids_antiguos = origen["id_unico"].astype(str).str.strip()
    if ids_antiguos[ids_antiguos.ne("")].duplicated().any():
        raise ValueError("Hay IDs duplicados en la hoja antigua. Corrígelos antes de migrar.")
    saldos = pd.to_numeric(origen["saldo"], errors="coerce")
    if saldos.isna().any() or (saldos < 0).any() or ((saldos % 1) != 0).any():
        raise ValueError("Hay saldos negativos o no numéricos en el histórico. Corregir antes de migrar.")

    lotes_v2 = tabla_fresca("traz_lotes_v2")
    eventos_v2 = tabla_fresca("traz_eventos_v2")
    existentes_lotes = set(lotes_v2["id_lote"].astype(str))
    existentes_eventos = set(eventos_v2["id_evento"].astype(str))
    otros_ids = set(lotes_v2.loc[lotes_v2["origen_registro"].astype(str) != "IMPORTADO_LEGACY", "id_lote"].astype(str))
    colision = set(ids_antiguos) & otros_ids
    if colision:
        raise ValueError(f"Hay IDs antiguos que coinciden con registros nuevos: {list(colision)[:4]}. Detenida la importación.")

    ahora_migracion = sello()
    nuevos_lotes, nuevos_eventos = [], []
    for _, x in origen.iterrows():
        id_lote = str(x["id_unico"]).strip()
        if not id_lote:
            continue
        saldo = entero(x.get("saldo", 0))
        if id_lote not in existentes_lotes:
            nuevos_lotes.append({
                "id_lote": id_lote, "id_raiz": id_lote, "id_padre": "",
                "lote_nro": x.get("lote_nro", ""), "procedencia": x.get("procedencia", ""),
                "planta": x.get("planta", ""), "granja": x.get("granja", ""),
                "descripcion": x.get("descripcion", ""), "genetica": x.get("linea_genetica", ""),
                "edad_repro": entero(x.get("edad_repro", 0)), "fecha_postura": x.get("fecha_postura", ""),
                "fecha_llegada": x.get("fecha_llegada", ""), "cantidad_origen": saldo,
                "obs_sanitarias": x.get("obs_sanitarias", ""),
                "origen_registro": "IMPORTADO_LEGACY", "fecha_creacion": ahora_migracion,
                "creado_por": responsable,
            })
        if saldo > 0 and ("LEG-" + id_lote) not in existentes_eventos:
            nuevos_eventos.append({
                "id_evento": "LEG-" + id_lote, "id_lote": id_lote, "id_raiz": id_lote,
                "tipo": "APERTURA_LEGACY", "cantidad": saldo, "variacion": saldo,
                "planta": x.get("planta", ""), "planta_contraparte": "", "id_traslado": "",
                "referencia": "SNAPSHOT DE MIGRACION", "fecha_evento": ahora_migracion,
                "responsable": responsable,
                "observaciones": "Saldo inicial importado. Los movimientos anteriores no recalculan este saldo.",
                "metadata_json": "{}",
            })
    # Primero las fichas maestras; después, los saldos iniciales. Si una operación
    # falla, al repetir se omiten IDs ya persistidos para evitar duplicaciones.
    append_varios("traz_lotes_v2", nuevos_lotes)
    append_varios("traz_eventos_v2", nuevos_eventos)
    return len(nuevos_lotes), len(nuevos_eventos)


def reparar_despacho_desde_documento(traslado: pd.Series, responsable: str):
    responsable = validar_responsable(responsable)
    if existe(tabla_fresca("traz_eventos_v2"), "id_evento", "ENV-" + str(traslado["id_traslado"])):
        return False
    cantidad = entero(traslado["cantidad_enviada"])
    if stock_fresco(str(traslado["id_lote_origen"])) < cantidad:
        raise ValueError("Saldo insuficiente para conciliar el despacho. Requiere revisión manual de eventos posteriores.")
    return registrar_evento(
        "ENV-" + str(traslado["id_traslado"]), str(traslado["id_lote_origen"]),
        str(traslado["id_raiz"]), "TRASLADO_ENVIO", cantidad, -cantidad,
        str(traslado["planta_origen"]), responsable,
        str(traslado["observaciones"]),
        planta_contraparte=str(traslado["planta_destino"]),
        id_traslado=str(traslado["id_traslado"]),
        referencia=str(traslado["guia"]), fecha_evento=str(traslado["fecha_envio"]),
    )


def reparar_recepcion_desde_evento(evento: pd.Series):
    """Completa la confirmación si se guardó el evento, pero no la recepción."""
    if str(evento["tipo"]) != "RECEPCION_TRASLADO":
        raise ValueError("El evento seleccionado no es una recepción.")
    info = json.loads(str(evento["metadata_json"] or "{}"))
    obligatorios = {"fecha_recepcion", "hora_recepcion", "aceptada", "rechazada", "faltante", "condicion"}
    if not obligatorios.issubset(info):
        raise ValueError("No hay datos suficientes para la reparación automática.")
    id_recep = str(evento["referencia"])
    if existe(tabla_fresca("traz_recepciones_v2"), "id_recepcion", id_recep):
        return False
    traslado = tabla_fresca("traz_traslados_v2")
    x = traslado[traslado["id_traslado"].astype(str) == str(evento["id_traslado"])]
    if x.empty:
        raise ValueError("No existe el documento de traslado asociado.")
    x = x.iloc[0]
    # El evento ya existe, de modo que NO debe crearse un segundo movimiento.
    if entero(evento["cantidad"]) != entero(info["aceptada"]):
        raise ValueError("La cantidad del evento difiere del respaldo de recepción.")
    append_registro("traz_recepciones_v2", {
        "id_recepcion": id_recep, "id_traslado": evento["id_traslado"],
        "id_lote_destino": x["id_lote_destino"],
        "fecha_recepcion": momento(date.fromisoformat(info["fecha_recepcion"]), dt_time.fromisoformat(info["hora_recepcion"])),
        "cantidad_aceptada": entero(info["aceptada"]),
        "cantidad_rechazada": entero(info["rechazada"]),
        "cantidad_faltante": entero(info["faltante"]),
        "temperatura_llegada": info.get("temperatura_llegada", ""),
        "condicion": info["condicion"], "observaciones": info.get("observaciones", ""),
        "responsable": evento["responsable"], "creado_en": sello(),
    })
    return True


# ────────────────────────────────── INTERFAZ ──────────────────────────────────
def titulo(nombre, descripcion):
    st.title(nombre)
    st.markdown(f'<div class="section-intro">{seguro(descripcion)}</div>', unsafe_allow_html=True)


def tabla(df: pd.DataFrame, altura=400):
    st.dataframe(df, use_container_width=True, hide_index=True, height=altura)


def etiqueta_lote(row):
    return f"{row['lote_nro']} · {row['planta']} · {row['id_lote']} · {entero(row['saldo']):,} huevos"


def elegir_lote(df, key, etiqueta="Seleccionar recepción/lote"):
    if df.empty:
        st.info("No hay lotes disponibles.")
        return None
    opciones = df.set_index("id_lote").to_dict("index")
    resultado = st.selectbox(etiqueta, list(opciones), format_func=lambda k: etiqueta_lote({**opciones[k], "id_lote": k}), key=key)
    return df[df["id_lote"] == resultado].iloc[0]


with st.sidebar:
    st.markdown('<div class="kicker">Control de Gestión</div>', unsafe_allow_html=True)
    st.markdown("### IncubaTrack 2.0")
    st.caption("Trazabilidad de huevo incubable")
    menu = st.radio(
        "Módulos", [
            "Resumen", "Recepciones", "Traslados entre plantas", "Salidas y ajustes",
            "Inventario", "Trazabilidad", "Auditoría y configuración",
        ], label_visibility="collapsed",
    )
    st.divider()
    responsable = st.text_input("Responsable que registra", value=st.session_state.get("operador", ""), placeholder="Nombre y apellido")
    st.session_state["operador"] = responsable
    edad_alerta = st.number_input("Alertar edad del huevo superior a (días)", min_value=1, max_value=60, value=10)
    if st.button("Actualizar datos", use_container_width=True):
        cargar_tabla.clear()
        st.rerun()
    st.caption("Los usuarios ingresados aquí no están autenticados. Implementar login antes del uso generalizado.")

try:
    preparar_hojas()
    lotes, eventos, traslados, recepciones = preparar_estado()
except Exception as error:
    st.error(f"No fue posible inicializar Google Sheets: {error}")
    st.info("Revisa los permisos de la cuenta de servicio y el archivo indicado en Streamlit Secrets.")
    st.stop()

if st.session_state.get("mensaje_exito"):
    st.toast(st.session_state.pop("mensaje_exito"), icon="✅")

if menu == "Resumen":
    titulo("Centro de control", "Visión consolidada por planta, stock disponible y traslados pendientes de recepción.")
    total = int(lotes["saldo"].sum())
    transito = int(traslados.loc[traslados["estado"].isin(["EN TRANSITO", "RECEPCION PARCIAL"]), "pendiente"].sum())
    pendientes = int(traslados["estado"].isin(["EN TRANSITO", "RECEPCION PARCIAL"]).sum())
    difer = int(traslados["cantidad_rechazada"].sum() + traslados["cantidad_faltante"].sum())
    vencidos = int(((lotes["saldo"] > 0) & (pd.to_numeric(lotes["dias_postura"], errors="coerce") > edad_alerta)).sum())
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Stock en plantas", f"{total:,}")
    m2.metric("Huevos en tránsito", f"{transito:,}")
    m3.metric("Traslados abiertos", f"{pendientes:,}")
    m4.metric("Rechazos + faltantes", f"{difer:,}")
    m5.metric("Recepciones en alerta", f"{vencidos:,}")
    st.caption("El tránsito no forma parte del stock físico disponible. Las diferencias se contabilizan solo cuando se registran en la recepción.")

    st.subheader("Existencias por planta")
    resumen = pd.DataFrame({"Planta": PLANTAS})
    agrup = lotes.groupby("planta")["saldo"].sum()
    resumen["Huevos disponibles"] = resumen["Planta"].map(agrup).fillna(0).astype(int)
    resumen["Recepciones activas"] = resumen["Planta"].map(lotes[lotes["saldo"] > 0].groupby("planta").size()).fillna(0).astype(int)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.bar_chart(resumen.set_index("Planta")[["Huevos disponibles"]], horizontal=True)
    with c2:
        tabla(resumen, 205)

    st.subheader("Seguimiento de transferencias")
    if traslados.empty:
        st.info("Sin traslados registrados todavía.")
    else:
        vista = traslados.sort_values("fecha_envio", ascending=False).head(12)
        tabla(vista[["id_traslado", "lote_nro", "planta_origen", "planta_destino", "cantidad_enviada", "cantidad_aceptada", "pendiente", "estado"]], 360)

    if vencidos:
        with st.expander(f"Ver {vencidos} recepciones con huevos de más de {edad_alerta} días desde postura"):
            alerta = lotes[(lotes["saldo"] > 0) & (pd.to_numeric(lotes["dias_postura"], errors="coerce") > edad_alerta)]
            tabla(alerta[["lote_nro", "id_lote", "planta", "saldo", "dias_postura", "dias_planta"]])

elif menu == "Recepciones":
    titulo("Recepción de huevos", "Registra huevos externos que llegan a una planta. Las transferencias internas se reciben en su módulo correspondiente.")
    with st.form("nuevo_ingreso", clear_on_submit=False):
        a, b, c = st.columns(3)
        lote_nro = a.text_input("Número de lote *")
        planta = b.selectbox("Planta receptora", PLANTAS)
        procedencia = c.selectbox("Procedencia", ["CDG", "San Fernando", "Santa Elena", "Otros"])
        a, b, c = st.columns(3)
        granja = a.text_input("Granja de origen")
        descripcion = b.selectbox("Tipo de huevo", DESCRIPCIONES)
        genetica = c.selectbox("Genética", GENETICAS)
        a, b, c, d = st.columns(4)
        edad_repro = a.number_input("Edad reproductoras (semanas)", min_value=0, max_value=120, value=0)
        cantidad = b.number_input("Huevos recibidos *", min_value=1, step=1, value=1)
        postura = c.date_input("Fecha postura", value=ahora().date())
        llegada = d.date_input("Fecha recepción", value=ahora().date())
        hora_llegada = st.time_input("Hora recepción", value=ahora().time().replace(second=0, microsecond=0))
        observaciones = st.text_area("Observaciones sanitarias / recepción", height=90)
        st.caption(f"ID de operación: {clave_borrador('ingreso', 'LOT')}")
        enviar = st.form_submit_button("Guardar recepción", type="primary")
    if enviar:
        try:
            identificador = clave_borrador("ingreso", "LOT")
            guardar_ingreso({
                "id_lote": identificador, "lote_nro": lote_nro, "planta": planta,
                "procedencia": procedencia, "granja": granja, "descripcion": descripcion,
                "genetica": genetica, "edad_repro": int(edad_repro), "cantidad": int(cantidad),
                "fecha_postura": postura, "fecha_llegada": llegada, "hora_llegada": hora_llegada,
                "observaciones": observaciones,
            }, responsable)
            nuevo_borrador("ingreso", "LOT")
            exito_y_recargar("Recepción registrada con trazabilidad inicial.")
        except Exception as error:
            st.error(f"No se pudo guardar: {error}. Conserva el ID del borrador y vuelve a intentar si hubo un corte de conexión.")
    st.info("Cada llegada es una unidad de inventario única, incluso cuando comparte el mismo número de lote productivo con otras recepciones.")

elif menu == "Traslados entre plantas":
    titulo("Traslados entre plantas", "Dos pasos separados: despacho desde origen y recepción física confirmada en destino.")
    tab_envio, tab_recep, tab_segui = st.tabs(["1 · Despachar", "2 · Confirmar recepción", "3 · Seguimiento"])
    with tab_envio:
        disponibles = lotes[lotes["saldo"] > 0].copy()
        if disponibles.empty:
            st.info("No hay stock disponible para despachar. Registra un ingreso o importa los saldos iniciales.")
        else:
            elegido = elegir_lote(disponibles, "lote_traslado")
            if elegido is not None:
                st.caption(f"Origen: {elegido['planta']} · Saldo actual: {elegido['saldo']:,} huevos · Lote raíz: {elegido['id_raiz']}")
                with st.form("form_traslado"):
                    destinos = [p for p in PLANTAS if p != elegido["planta"]]
                    destino = st.selectbox("Planta destino", destinos)
                    a, b, c = st.columns(3)
                    cantidad_env = a.number_input("Cantidad a despachar", min_value=1, max_value=max(1, int(elegido["saldo"])), value=1)
                    fecha_env = b.date_input("Fecha salida", value=ahora().date())
                    hora_env = c.time_input("Hora salida", value=ahora().time().replace(second=0, microsecond=0))
                    a, b, c = st.columns(3)
                    guia = a.text_input("Guía / documento")
                    transporte = b.text_input("Transportista")
                    placa = c.text_input("Placa del vehículo")
                    a, b = st.columns(2)
                    logtag = a.text_input("Código LogTag")
                    temp_sal = b.number_input("Temperatura salida °C (referencial)", value=0.0, step=0.1, help="Si no hay medición, dejar en cero; no se interpreta como 0 °C.")
                    nota = st.text_area("Observaciones del traslado", height=80)
                    st.caption(f"ID de envío: {clave_borrador('traslado', 'TRF')}")
                    ejecutar_env = st.form_submit_button("Confirmar despacho", type="primary")
                if ejecutar_env:
                    try:
                        id_tra = clave_borrador("traslado", "TRF")
                        guardar_traslado({
                            "id_traslado": id_tra, "id_lote_origen": elegido["id_lote"],
                            "id_lote_destino": f"REC-{id_tra}", "id_raiz": elegido["id_raiz"],
                            "planta_origen": elegido["planta"], "planta_destino": destino,
                            "cantidad_enviada": int(cantidad_env), "fecha_salida": fecha_env,
                            "hora_salida": hora_env, "guia": guia.strip(), "transportista": transporte.strip(),
                            "placa": placa.strip().upper(), "logtag": logtag.strip(),
                            "temperatura_salida": "" if temp_sal == 0 else temp_sal,
                            "observaciones": nota,
                        }, responsable)
                        nuevo_borrador("traslado", "TRF")
                        exito_y_recargar("Despacho registrado: los huevos figuran en tránsito hasta confirmarse la recepción.")
                    except Exception as error:
                        st.error(f"No se pudo completar el despacho: {error}. No cambies el ID del borrador al reintentar.")

    with tab_recep:
        abiertos = traslados[traslados["estado"].isin(["EN TRANSITO", "RECEPCION PARCIAL"])].copy()
        if abiertos.empty:
            st.info("No hay traslados pendientes de recepción.")
        else:
            opciones = abiertos.set_index("id_traslado").to_dict("index")
            id_actual = st.selectbox("Traslado pendiente", list(opciones), format_func=lambda k: f"{k} | {opciones[k]['planta_origen']} → {opciones[k]['planta_destino']} | {opciones[k]['pendiente']:,} pendientes")
            x = opciones[id_actual]
            st.caption(f"Lote {x['lote_nro']} · Enviado {entero(x['cantidad_enviada']):,} · Aceptado {entero(x['cantidad_aceptada']):,} · Pendiente {entero(x['pendiente']):,}")
            with st.form("form_recepcion_traslado"):
                a, b, c = st.columns(3)
                fecha_rec = a.date_input("Fecha de llegada", value=ahora().date())
                hora_rec = b.time_input("Hora llegada", value=ahora().time().replace(second=0, microsecond=0))
                condicion = c.selectbox("Condición de recepción", ["Conforme", "Con observaciones", "No conforme"])
                a, b, c = st.columns(3)
                aceptada = a.number_input("Huevos aceptados", min_value=0, max_value=max(0, int(x["pendiente"])), value=int(x["pendiente"]))
                rechazados = b.number_input("Huevos rechazados", min_value=0, max_value=max(0, int(x["pendiente"])), value=0)
                faltantes = c.number_input("Huevos faltantes (cierre de diferencia)", min_value=0, max_value=max(0, int(x["pendiente"])), value=0)
                temp_llegada = st.number_input("Temperatura llegada °C (referencial)", value=0.0, step=0.1)
                obs_rec = st.text_area("Observaciones y explicación de diferencias", height=90)
                st.caption(f"ID de confirmación: {clave_borrador('recepcion', 'RCP')}")
                confirmar = st.form_submit_button("Confirmar recepción", type="primary")
            if confirmar:
                try:
                    identificador = clave_borrador("recepcion", "RCP")
                    guardar_recepcion_traslado({
                        "id_recepcion": identificador, "id_traslado": id_actual,
                        "fecha_recepcion": fecha_rec, "hora_recepcion": hora_rec,
                        "aceptada": int(aceptada), "rechazada": int(rechazados),
                        "faltante": int(faltantes), "condicion": condicion,
                        "temperatura_llegada": "" if temp_llegada == 0 else temp_llegada,
                        "observaciones": obs_rec,
                    }, responsable)
                    nuevo_borrador("recepcion", "RCP")
                    exito_y_recargar("Llegada confirmada. Stock de destino actualizado y vinculado al origen.")
                except Exception as error:
                    st.error(f"No se pudo confirmar: {error}. Conserva el ID de confirmación para reintentar.")
            st.caption("En una recepción parcial, registra únicamente lo efectivamente aceptado/rechazado. Los huevos restantes continúan en tránsito hasta el siguiente registro o cierre por faltante.")

    with tab_segui:
        if traslados.empty:
            st.info("Aún no se han registrado despachos.")
        else:
            filtro = st.selectbox("Estado", ["TODOS"] + sorted(traslados["estado"].unique().tolist()))
            vista = traslados if filtro == "TODOS" else traslados[traslados["estado"] == filtro]
            tabla(vista[["id_traslado", "lote_nro", "planta_origen", "planta_destino", "cantidad_enviada", "cantidad_aceptada", "cantidad_rechazada", "cantidad_faltante", "pendiente", "estado", "fecha_envio", "guia", "logtag"]], 450)
            st.download_button("Exportar seguimiento", excel_hojas({"Traslados": vista}), file_name="Traslados_IncubaTrack.xlsx")

elif menu == "Salidas y ajustes":
    titulo("Destinos y correcciones", "Registra cargas de incubadora, ventas, mermas y ajustes documentados sin modificar manualmente el saldo.")
    disponibles = lotes[lotes["saldo"] > 0].copy()
    elegir = elegir_lote(disponibles, "lote_salida")
    if elegir is not None:
        with st.form("form_salida"):
            tipo_etiqueta = st.selectbox("Operación", ["Carga incubadora", "Venta", "Merma", "Ajuste negativo", "Ajuste positivo"])
            tipo = {"Carga incubadora": "SALIDA_INCUBADORA", "Venta": "VENTA", "Merma": "MERMA", "Ajuste negativo": "AJUSTE_NEGATIVO", "Ajuste positivo": "AJUSTE_POSITIVO"}[tipo_etiqueta]
            cantidad_sal = st.number_input("Cantidad", min_value=1, value=1, step=1)
            ref = st.text_input("Incubadora / N° carga / documento de referencia", placeholder="Ej.: INC-04 / CARGA-2026-125")
            obs = st.text_area("Justificación / observaciones", height=100)
            st.caption(f"ID movimiento: {clave_borrador('salida', 'MOV')}")
            guardar = st.form_submit_button("Registrar movimiento", type="primary")
        if guardar:
            try:
                guardar_salida({"id_evento": clave_borrador("salida", "MOV"),
                                "id_lote": elegir["id_lote"], "tipo": tipo,
                                "cantidad": int(cantidad_sal), "referencia": ref, "observaciones": obs}, responsable)
                nuevo_borrador("salida", "MOV")
                exito_y_recargar("Movimiento registrado. El stock se recalculó desde los eventos.")
            except Exception as error:
                st.error(f"Error al registrar: {error}")
        st.warning("Los ajustes no sustituyen una investigación de diferencias. No se permiten borrados de movimientos desde la interfaz.")

elif menu == "Inventario":
    titulo("Inventario por recepción", "Cada registro mantiene su planta, fecha de recepción, antigüedad desde postura y saldo calculado.")
    activos = lotes[lotes["saldo"] > 0].copy()
    a, b, c = st.columns(3)
    filtro_planta = a.selectbox("Planta", ["TODAS"] + PLANTAS)
    buscar = b.text_input("Buscar lote, granja o ID")
    solo_alertas = c.checkbox(f"Solo huevos con más de {edad_alerta} días desde postura")
    vista = activos.copy()
    if filtro_planta != "TODAS":
        vista = vista[vista["planta"] == filtro_planta]
    if buscar:
        patron = buscar.strip()
        mascara = (vista["lote_nro"].astype(str).str.contains(patron, case=False, regex=False)
                   | vista["id_lote"].astype(str).str.contains(patron, case=False, regex=False)
                   | vista["granja"].astype(str).str.contains(patron, case=False, regex=False))
        vista = vista[mascara]
    if solo_alertas:
        vista = vista[pd.to_numeric(vista["dias_postura"], errors="coerce") > edad_alerta]
    vista["Estado edad"] = vista["dias_postura"].apply(
        lambda d: "Sin fecha" if pd.isna(d) else "Alerta" if d > edad_alerta else "Observación" if d >= max(1, edad_alerta - 2) else "Dentro de umbral"
    )
    a, b, c = st.columns(3)
    a.metric("Stock filtrado", f"{int(vista['saldo'].sum()):,}")
    b.metric("Recepciones", len(vista))
    valido = vista.dropna(subset=["dias_postura"])
    peso = valido["saldo"].sum()
    edad_media = round((valido["dias_postura"] * valido["saldo"]).sum() / peso, 1) if peso > 0 else 0
    c.metric("Edad ponderada del huevo", f"{edad_media} días")
    campos = ["id_lote", "lote_nro", "planta", "procedencia", "granja", "saldo", "fecha_postura", "fecha_llegada", "dias_postura", "dias_planta", "edad_repro", "Estado edad"]
    tabla(vista[campos].sort_values("dias_postura", ascending=False, na_position="last"), 480)
    st.caption("Edad desde postura ≠ días almacenados en la planta. Ambos valores se muestran por separado. El umbral debe validarse con los procedimientos técnicos de Incubación.")
    st.download_button("Exportar inventario filtrado", excel_hojas({"Inventario": vista[campos]}), file_name="Inventario_IncubaTrack.xlsx")

elif menu == "Trazabilidad":
    titulo("Expediente de trazabilidad", "Consulta todo el recorrido de un lote productivo, incluyendo derivaciones y nuevas recepciones entre plantas.")
    if lotes.empty:
        st.info("Primero registra o importa lotes.")
    else:
        vista_raices = lotes.drop_duplicates("id_raiz").copy()
        listado_raices = vista_raices.set_index("id_raiz").to_dict("index")
        raiz = st.selectbox("Lote / recepción raíz", list(listado_raices), format_func=lambda x: f"{listado_raices[x]['lote_nro']} · {listado_raices[x]['procedencia']} · {x}")
        familia = lotes[lotes["id_raiz"] == raiz].copy()
        movimientos = eventos[eventos["id_raiz"] == raiz].sort_values("fecha_evento", ascending=True).copy()
        rutas = traslados[traslados["id_raiz"] == raiz].copy()
        detalle_rec = recepciones[recepciones["id_traslado"].isin(rutas["id_traslado"])].copy()
        a, b, c, d = st.columns(4)
        a.metric("Saldo actual de la familia", f"{int(familia['saldo'].sum()):,}")
        b.metric("Recepciones vinculadas", len(familia))
        c.metric("Plantas en el recorrido", int(familia["planta"].nunique()))
        d.metric("Transferencias realizadas", len(rutas))
        st.subheader("Árbol de recepciones")
        def nivel(x):
            actual = str(x["id_padre"])
            visitados = {str(x["id_lote"])}
            n = 0
            dic = familia.set_index("id_lote")["id_padre"].to_dict()
            while actual and actual not in visitados and n < 20:
                n += 1
                visitados.add(actual)
                actual = str(dic.get(actual, ""))
            return n
        familia["Etapa"] = familia.apply(nivel, axis=1)
        tabla(familia[["Etapa", "id_lote", "id_padre", "lote_nro", "planta", "fecha_llegada", "saldo", "origen_registro"]].sort_values(["Etapa", "fecha_llegada"]), 320)
        st.subheader("Línea de tiempo de movimientos")
        tabla(movimientos[["fecha_evento", "tipo", "planta", "planta_contraparte", "cantidad", "variacion", "referencia", "id_lote", "responsable"]], 400)
        if not rutas.empty:
            st.subheader("Rutas y conciliación entre plantas")
            tabla(rutas[["id_traslado", "planta_origen", "planta_destino", "cantidad_enviada", "cantidad_aceptada", "cantidad_rechazada", "cantidad_faltante", "pendiente", "estado", "guia", "logtag"]], 320)
        exportar = {"Lotes": familia, "Movimientos": movimientos, "Traslados": rutas, "Recepciones": detalle_rec}
        try:
            historicos = pd.DataFrame(hoja("movimientos").get_all_records(default_blank=""))
            if {"id_lote"}.issubset(historicos.columns):
                historicos = historicos[historicos["id_lote"].astype(str).isin(familia["id_lote"].astype(str))]
                if not historicos.empty:
                    st.subheader("Antecedentes del sistema anterior")
                    st.caption("Referencia histórica únicamente; no se suma al stock de IncubaTrack 2.0.")
                    tabla(historicos, 220)
                    exportar["Histórico anterior"] = historicos
        except gspread.exceptions.WorksheetNotFound:
            pass
        st.download_button("Descargar expediente completo", excel_hojas(exportar), file_name=f"Trazabilidad_{raiz}.xlsx", type="primary")

elif menu == "Auditoría y configuración":
    titulo("Auditoría y configuración", "Revisa la consistencia entre envíos, recepciones y eventos; importa los saldos del sistema anterior sin modificarlo.")
    incidencias = diagnosticos(lotes, eventos, traslados, recepciones)
    a, b, c = st.columns(3)
    a.metric("Incidencias de integridad", len(incidencias))
    b.metric("Eventos registrados", len(eventos))
    c.metric("Lotes / recepciones", len(lotes))
    if incidencias.empty:
        st.success("Sin incoherencias detectadas por los controles automatizados.")
    else:
        st.error("Se detectaron inconsistencias. Revisarlas antes de interpretar los KPIs.")
        tabla(incidencias, 350)

    with st.expander("Ver todos los eventos registrados"):
        tabla(eventos.sort_values("fecha_evento", ascending=False), 460)
    envios_incompletos = traslados[traslados["estado"] == "SIN DESPACHO"]
    if not envios_incompletos.empty:
        with st.expander("Recuperación de documentos de despacho incompletos", expanded=True):
            st.warning("Estos documentos existen, pero no tienen evento de salida. Comprobar antes que el envío salió físicamente.")
            ops_envio = envios_incompletos.set_index("id_traslado").to_dict("index")
            referencia_envio = st.selectbox("Documento a recuperar", list(ops_envio))
            confirmar_envio = st.checkbox("Confirmo físicamente el despacho y autorizo descontar el stock")
            if st.button("Recuperar movimiento de despacho", disabled=not confirmar_envio):
                try:
                    reparar_despacho_desde_documento(envios_incompletos[envios_incompletos["id_traslado"] == referencia_envio].iloc[0], responsable)
                    exito_y_recargar("Evento de despacho recuperado sin duplicarlo.")
                except Exception as error:
                    st.error(f"No se pudo recuperar: {error}")
    con_error = eventos[(eventos["tipo"] == "RECEPCION_TRASLADO") &
                         (~eventos["referencia"].astype(str).isin(recepciones["id_recepcion"].astype(str)))]
    if not con_error.empty:
        with st.expander("Recuperación de recepciones interrumpidas", expanded=True):
            st.warning("Estas recepciones tienen entrada registrada, pero falta la confirmación. Revisa el documento físico antes de completarlas.")
            ops = con_error.set_index("id_evento").to_dict("index")
            oper = st.selectbox("Evento para completar", list(ops), key="recuperar_evento")
            st.write(f"ID: {ops[oper]['referencia']} · Traslado: {ops[oper]['id_traslado']} · Aceptados: {ops[oper]['cantidad']:,}")
            confirmar_recuperacion = st.checkbox("Confirmo que el evento coincide con la recepción física", key="recuperar_confirma")
            if st.button("Completar confirmación desde evento", disabled=not confirmar_recuperacion):
                try:
                    reparar_recepcion_desde_evento(con_error[con_error["id_evento"] == oper].iloc[0])
                    exito_y_recargar("Confirmación recuperada sin duplicar stock.")
                except Exception as error:
                    st.error(f"No se pudo recuperar: {error}")
    with st.expander("Importar saldos actuales desde las hojas antiguas"):
        st.warning("Realizar COPIA DE SEGURIDAD y detener la app anterior antes de importar. Esta operación es una fotografía de saldos actuales, no una reconstrucción retroactiva de movimientos.")
        st.write("La aplicación conserva intactas **lotes** y **movimientos**. Solo agregará datos faltantes a las hojas nuevas.")
        st.write("La migración se puede reintentar si se corta la conexión: comprueba los IDs antes de volver a escribir.")
        confirmar = st.checkbox("Confirmo que tengo respaldo de la hoja antigua y que suspendí registros en la app anterior.")
        if st.button("Importar / reanudar migración", disabled=not confirmar, type="primary"):
            try:
                with st.spinner("Importando registros existentes..."):
                    n_lotes, n_saldos = migrar_desde_legacy(responsable)
                exito_y_recargar(f"Importación terminada: {n_lotes} lotes nuevos y {n_saldos} saldos iniciales agregados.")
            except Exception as error:
                st.error(f"No se pudo completar la importación: {error}")

    st.subheader("Paquete de auditoría")
    st.download_button("Exportar libro completo", excel_hojas({
        "Inventario": lotes, "Eventos": eventos, "Traslados": traslados,
        "Recepciones": recepciones, "Alertas": incidencias,
    }), file_name=f"Auditoria_IncubaTrack_{ahora():%Y%m%d}.xlsx", type="primary")
    st.info("Limitación: Google Sheets carece de transacciones multihoja, bloqueo distribuido y autenticación de usuario en esta app. Para operación simultánea crítica, usar base transaccional y acceso por roles.")

st.divider()
st.caption("IncubaTrack 2.0 · Control de Gestión · Registro de movimientos trazables entre plantas")
