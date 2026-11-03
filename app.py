"""IncubaTrack | P.I. Pucacaca - Almacén de huevos incubables.

Streamlit + Google Sheets (hojas nuevas separadas) y modo demo temporal.
Importa el Excel «Control Almacen de HI DonPollo.xlsx» SIN alterar el archivo.

Regla de negocio: saldo = ingresos + sumatoria de movimientos firmados.
Las clases OK / R / RR son independientes. Una carga es SALIDA de almacén;
el paso incubadora -> nacedora no es un nuevo movimiento de almacén.

LIMITACIÓN: Google Sheets no dispone de transacciones o bloqueo multiusuario.
Para operación con varios operadores simultáneos se recomienda PostgreSQL.
"""
from __future__ import annotations

import collections
import hashlib
import html
import io
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

TZ = ZoneInfo("America/Lima")
PLANTA = "P.I. Pucacaca"
DESTINO = "P.I. Tarapoto"
HI_POR_CAJA = 360
TIPOS_HI = ("OK", "R", "RR")
TIPOS_MOV = ("CARGA", "TRANSFERENCIA", "BAJA", "AJUSTE +", "AJUSTE -")
ORIGENES = ("Granja", "Transferencia recibida", "Saldo inicial", "Otro")
NAMESPACE = uuid.UUID("e812b4ba-3c87-4ca5-a687-507555714918")

RECEPCION = [
    "id_recepcion", "lote", "fecha_postura", "edad_repro", "tipo_hi",
    "fecha_ingreso", "cantidad_hi", "ubicacion", "guia_recepcion", "origen",
    "responsable", "observacion", "codigo_excel", "fila_excel", "creado_en", "importacion_id",
]
MOVIMIENTO = [
    "id_movimiento", "id_operacion", "fecha_movimiento", "tipo", "id_recepcion",
    "cantidad_hi", "variacion_hi", "incubadora", "destino", "documento",
    "responsable", "causa", "observacion", "transportista", "placa",
    "logtag", "creado_en", "importacion_id", "fila_excel",
]
CONTEO = [
    "id_conteo", "fecha_conteo", "id_recepcion", "saldo_sistema",
    "conteo_fisico", "diferencia", "documento", "responsable", "observacion", "creado_en",
]
CONFIRMACION = [
    "id_confirmacion", "id_operacion", "fecha_recepcion", "recibidos_hi", "rechazados_hi",
    "faltantes_hi", "documento", "responsable", "observacion", "creado_en",
]
SHEETS = {
    "HI_PUC_Recepciones": RECEPCION,
    "HI_PUC_Movimientos": MOVIMIENTO,
    "HI_PUC_Conteos": CONTEO,
    "HI_PUC_Confirmaciones": CONFIRMACION,
}
MAP_SHEET = {"recepciones": "HI_PUC_Recepciones", "movimientos": "HI_PUC_Movimientos",
             "conteos": "HI_PUC_Conteos", "confirmaciones": "HI_PUC_Confirmaciones"}


def ahora() -> datetime:
    return datetime.now(TZ)


def timestamp() -> str:
    return ahora().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{ahora():%y%m%d}-{uuid.uuid4().hex[:10].upper()}"


def i_num(v, default=0) -> int:
    try:
        if v is None or str(v).strip() == "":
            return default
        n = float(str(v).replace(",", ""))
        if n != n or not n.is_integer():
            return default
        return int(n)
    except (ValueError, TypeError, OverflowError):
        return default


def plain(v) -> str:
    return str(v if v is not None else "").strip()


def clean_lote(v) -> str:
    s = plain(v)
    if re.fullmatch(r"[0-9]+(?:\.0+)?", s):
        return str(int(float(s)))
    return s.upper()


def date_iso(v) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = plain(v)
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError:
        return s[:10]


def parse_date(v) -> date | None:
    try:
        return date.fromisoformat(date_iso(v))
    except (ValueError, TypeError):
        return None


def date_excel(v, mantener_hora=False) -> str:
    if isinstance(v, (int, float)):
        try:
            fecha = datetime(1899, 12, 30) + timedelta(days=float(v))
            if mantener_hora and fecha.time().hour + fecha.time().minute + fecha.time().second:
                return fecha.isoformat(timespec="seconds")
            return fecha.date().isoformat()
        except (ValueError, OverflowError):
            return ""
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(v.strip(), fmt).date().isoformat()
            except ValueError:
                pass
        return date_iso(v)
    return ""


def datetime_postura(v) -> datetime | None:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).strip()).replace(tzinfo=None)
    except ValueError:
        return None


def etiqueta_postura(v) -> str:
    fecha = datetime_postura(v)
    if fecha is None:
        return plain(v)
    return fecha.strftime("%Y-%m-%d %H:%M") if fecha.hour or fecha.minute else fecha.date().isoformat()


def num_format(v) -> str:
    return f"{i_num(v):,}".replace(",", " ")


def classify_age(edad: int, rules: tuple[int, int, int]) -> int:
    return rules[0] if edad < 50 else (rules[1] if edad < 60 else rules[2])


def inventario(recepciones: list[dict], movimientos: list[dict], corte: date,
               reglas: tuple[int, int, int] = (7, 5, 3)) -> list[dict]:
    """Inventario al corte, basado solo en eventos, sin escribir saldos."""
    cambios = collections.defaultdict(int)
    for m in movimientos:
        fecha = parse_date(m.get("fecha_movimiento"))
        if fecha and fecha <= corte:
            cambios[plain(m.get("id_recepcion"))] += i_num(m.get("variacion_hi"))
    salida = []
    for r in recepciones:
        fi = parse_date(r.get("fecha_ingreso"))
        fp = datetime_postura(r.get("fecha_postura"))
        if not fi or fi > corte:
            continue
        cantidad = i_num(r.get("cantidad_hi"))
        saldo = cantidad + cambios.get(plain(r.get("id_recepcion")), 0)
        edad = i_num(r.get("edad_repro"))
        objetivo = classify_age(edad, reglas) if edad > 0 else None
        dias = round((datetime.combine(corte, datetime.min.time()) - fp).total_seconds() / 86400, 2) if fp else None
        faltan = objetivo - dias if objetivo is not None and dias is not None else None
        estado = ("Sin saldo" if saldo == 0 else "Saldo negativo" if saldo < 0 else
                  "Sin fecha" if faltan is None else
                  "Objetivo superado" if faltan < 0 else
                  "Cargar hoy" if faltan == 0 else
                  "Próximo objetivo" if faltan <= 1 else "En plazo")
        salida.append({
            "id_recepcion": plain(r.get("id_recepcion")),
            "lote": clean_lote(r.get("lote")),
            "fecha_postura": plain(r.get("fecha_postura")),
            "edad_repro": edad,
            "tipo_hi": plain(r.get("tipo_hi")).upper(),
            "fecha_ingreso": date_iso(r.get("fecha_ingreso")),
            "guia_recepcion": plain(r.get("guia_recepcion")),
            "ubicacion": plain(r.get("ubicacion")),
            "origen": plain(r.get("origen")),
            "responsable": plain(r.get("responsable")),
            "codigo_excel": plain(r.get("codigo_excel")),
            "ingresos_hi": cantidad,
            "movimientos_hi": cambios.get(plain(r.get("id_recepcion")), 0),
            "saldo_hi": saldo,
            "cajas": max(0, saldo) // HI_POR_CAJA,
            "adicionales": max(0, saldo) % HI_POR_CAJA,
            "dias_postura": dias,
            "objetivo_dias": objetivo,
            "dias_restantes": faltan,
            "estado": estado,
        })
    return salida


def estadisticas(inventario_rows: list[dict], movimientos: list[dict], corte: date) -> dict:
    r = inventario_rows
    vistos = {x["id_recepcion"] for x in r}
    mv = [m for m in movimientos if plain(m.get("id_recepcion")) in vistos and
          (d := parse_date(m.get("fecha_movimiento"))) and d <= corte]
    saldos = sum(x["saldo_hi"] for x in r)
    return {
        "ingresos": sum(x["ingresos_hi"] for x in r),
        "saldo": saldos,
        "cargados": sum(i_num(m.get("cantidad_hi")) for m in mv if plain(m.get("tipo")) == "CARGA"),
        "transferidos": sum(i_num(m.get("cantidad_hi")) for m in mv if plain(m.get("tipo")) == "TRANSFERENCIA"),
        "bajas": sum(i_num(m.get("cantidad_hi")) for m in mv if plain(m.get("tipo")) == "BAJA"),
        "ajustes_mas": sum(i_num(m.get("cantidad_hi")) for m in mv if plain(m.get("tipo")) == "AJUSTE +"),
        "ajustes_menos": sum(i_num(m.get("cantidad_hi")) for m in mv if plain(m.get("tipo")) == "AJUSTE -"),
        "prioridad": sum(x["saldo_hi"] for x in r if x["saldo_hi"] > 0 and x["estado"] in ("Objetivo superado", "Cargar hoy", "Próximo objetivo")),
        "grupos": sum(x["saldo_hi"] > 0 for x in r),
        "cajas": max(0, saldos) // HI_POR_CAJA,
        "adicionales": max(0, saldos) % HI_POR_CAJA,
        "promedio_dias": round(sum(x["dias_postura"] * x["saldo_hi"] for x in r if x["dias_postura"] is not None and x["saldo_hi"] > 0) /
                               sum(x["saldo_hi"] for x in r if x["saldo_hi"] > 0), 1) if any(x["saldo_hi"] > 0 for x in r) else 0,
    }


def validar_movimientos(nuevos: list[dict], registros: dict, corte: date) -> None:
    if not nuevos:
        raise ValueError("Seleccione cantidades superiores a cero.")
    existentes = registros["movimientos"]
    ids = {plain(m.get("id_movimiento")) for m in existentes}
    if any(plain(m.get("id_movimiento")) in ids for m in nuevos):
        raise ValueError("La operación ya fue registrada. Actualice la página para ver el resultado.")
    totales = collections.defaultdict(int)
    estado = {r["id_recepcion"]: r for r in inventario(registros["recepciones"], existentes, corte)}
    for m in nuevos:
        tipo = plain(m.get("tipo"))
        cantidad = i_num(m.get("cantidad_hi"))
        if tipo not in TIPOS_MOV or cantidad <= 0:
            raise ValueError("Tipo de movimiento o cantidad inválida.")
        if date_iso(m.get("fecha_movimiento")) != corte.isoformat():
            raise ValueError("El movimiento debe validarse contra su fecha operativa.")
        rid = plain(m.get("id_recepcion"))
        if rid not in estado:
            raise ValueError("La recepción no existe al corte de la operación.")
        if not plain(m.get("documento")) or not plain(m.get("responsable")):
            raise ValueError("El documento y el responsable son obligatorios.")
        if tipo == "CARGA" and not plain(m.get("incubadora")):
            raise ValueError("Indique la incubadora de cada carga.")
        if tipo == "TRANSFERENCIA" and plain(m.get("destino")) != DESTINO:
            raise ValueError("En esta etapa solo se registran transferencias a P.I. Tarapoto.")
        if tipo in ("AJUSTE +", "AJUSTE -", "BAJA") and not plain(m.get("causa")):
            raise ValueError("Los ajustes y bajas requieren un motivo o causa.")
        variacion = cantidad if tipo == "AJUSTE +" else -cantidad
        if i_num(m.get("variacion_hi")) != variacion:
            raise ValueError("La variación no coincide con el tipo de operación.")
        totales[rid] += variacion
    for rid, delta in totales.items():
        if estado[rid]["saldo_hi"] + delta < 0:
            raise ValueError(f"Saldo insuficiente para lote {estado[rid]['lote']} / recepción {rid}.")
    # También validar todos los saldos cronológicos posteriores: una operación
    # retroactiva no debe dejar el almacén negativo tras cargas más recientes.
    cambios = set(totales)
    base = {r["id_recepcion"]: r for r in registros["recepciones"]
            if plain(r.get("id_recepcion")) in cambios}
    for rid in cambios:
        rec = base.get(rid)
        if not rec:
            raise ValueError("No se encontró la recepción vinculada.")
        balance = i_num(rec.get("cantidad_hi"))
        fecha_ingreso = parse_date(rec.get("fecha_ingreso"))
        por_dia = collections.defaultdict(int)
        for m in existentes + nuevos:
            if plain(m.get("id_recepcion")) != rid:
                continue
            d = parse_date(m.get("fecha_movimiento"))
            if not d or (fecha_ingreso and d < fecha_ingreso):
                raise ValueError("Existe un movimiento sin fecha válida o anterior a su recepción.")
            por_dia[d] += i_num(m.get("variacion_hi"))
        for fecha in sorted(por_dia):
            balance += por_dia[fecha]
            if balance < 0:
                raise ValueError(f"Saldo insuficiente: el lote {estado[rid]['lote']} quedaría negativo al {fecha}.")


def incidencias(registros: dict, inv_rows: list[dict]) -> list[dict]:
    lista = []
    ids = collections.Counter(plain(r.get("id_recepcion")) for r in registros["recepciones"])
    codigos = collections.Counter(plain(r.get("codigo_excel")) for r in registros["recepciones"]
                                  if plain(r.get("codigo_excel")))
    for code, n in codigos.items():
        if n > 1:
            lista.append({"Severidad": "Revisar", "Área": "Recepciones", "Referencia": code,
                          "Observación": f"Código histórico repetido en {n} recepciones; se conservaron con IDs independientes."})
    for k, n in ids.items():
        if n > 1:
            lista.append({"Severidad": "Crítico", "Área": "Recepciones", "Referencia": k,
                          "Observación": "ID interno duplicado; verificar escritura."})
    recep_ids = {r["id_recepcion"] for r in inv_rows}
    for m in registros["movimientos"]:
        rid = plain(m.get("id_recepcion"))
        referencia = plain(m.get("id_operacion")) or plain(m.get("id_movimiento"))
        if rid not in {plain(r.get("id_recepcion")) for r in registros["recepciones"]}:
            lista.append({"Severidad": "Crítico", "Área": "Movimientos", "Referencia": referencia, "Observación": "ID de recepción inexistente."})
        if not plain(m.get("documento")):
            lista.append({"Severidad": "Revisar", "Área": "Movimientos", "Referencia": referencia,
                          "Observación": "Falta documento de movimiento."})
        if plain(m.get("tipo")) == "CARGA" and not plain(m.get("incubadora")):
            lista.append({"Severidad": "Revisar", "Área": "Cargas", "Referencia": referencia,
                          "Observación": "Falta identificación de incubadora."})
    for r in inv_rows:
        if r["saldo_hi"] < 0:
            lista.append({"Severidad": "Crítico", "Área": "Saldos", "Referencia": r["id_recepcion"],
                          "Observación": "Saldo negativo."})
    return lista


# ─────────────── EXCEL: LECTURA DEL ARCHIVO SIN CAMBIOS ───────────────
XML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def leer_filas_xlsx(contenido: bytes, nombre_hoja: str) -> list[dict]:
    """Lee los valores cacheados de XLSX, incluidos ID calculados por fórmulas."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        relaciones = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {x.attrib["Id"]: x.attrib["Target"] for x in relaciones}
        sheet = next((x for x in workbook.iter(f"{{{XML_NS}}}sheet") if x.attrib.get("name") == nombre_hoja), None)
        if sheet is None:
            raise ValueError(f"La hoja requerida '{nombre_hoja}' no existe en el Excel.")
        ident = sheet.attrib[f"{{{REL_NS}}}id"]
        target = targets.get(ident, "")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if ".." in path.split("/"):
            raise ValueError("Ruta de hoja inválida.")
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            string_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.iter(f"{{{XML_NS}}}t"))
                       for si in string_root.findall(f"{{{XML_NS}}}si")]
        xml = ET.fromstring(z.read(path))
        resultado = []
        for row in xml.findall(f".//{{{XML_NS}}}sheetData/{{{XML_NS}}}row"):
            nr = int(row.attrib.get("r", "0"))
            registro = {"_fila": nr}
            for c in row.findall(f"{{{XML_NS}}}c"):
                col = re.match(r"[A-Z]+", c.attrib.get("r", ""))
                if not col:
                    continue
                v = c.find(f"{{{XML_NS}}}v")
                tipo = c.attrib.get("t", "")
                raw = v.text if v is not None else None
                if tipo == "s" and raw is not None:
                    raw = strings[int(raw)]
                elif tipo == "inlineStr":
                    raw = "".join(t.text or "" for t in c.iter(f"{{{XML_NS}}}t"))
                elif tipo == "n" or not tipo:
                    if raw is not None:
                        try:
                            raw = float(raw)
                        except ValueError:
                            pass
                registro[col.group(0)] = raw
            resultado.append(registro)
        return resultado


def preparar_importacion_excel(contenido: bytes) -> dict:
    digest = hashlib.sha256(contenido).hexdigest()
    batch_id = "XLSX-" + digest[:18].upper()
    rows_r = leer_filas_xlsx(contenido, "Existencias")
    rows_m = leer_filas_xlsx(contenido, "Movimientos")
    rec, mov, pendientes = [], [], []
    lookup = collections.defaultdict(list)
    for r in rows_r:
        if r["_fila"] < 10 or r["_fila"] > 439 or not clean_lote(r.get("B")):
            continue
        cantidad = i_num(r.get("G"))
        fp, fi = date_excel(r.get("C"), mantener_hora=True), date_excel(r.get("F"))
        tipo = plain(r.get("E")).upper()
        if cantidad <= 0 or not parse_date(fp) or not parse_date(fi) or tipo not in TIPOS_HI:
            pendientes.append(f"Existencias fila {r['_fila']}: datos mínimos inválidos; no se importa.")
            continue
        ident = "REC-" + str(uuid.uuid5(NAMESPACE, digest + ":R:" + str(r["_fila"]))).replace("-", "")[:20].upper()
        codigo = plain(r.get("A"))
        nuevo = dict(zip(RECEPCION, [
            ident, clean_lote(r.get("B")), fp, i_num(r.get("D")), tipo,
            fi, cantidad, plain(r.get("H")), plain(r.get("I")), plain(r.get("J")) or "Granja",
            plain(r.get("K")), plain(r.get("L")), codigo, r["_fila"], timestamp(), batch_id,
        ]))
        rec.append(nuevo)
        lookup[codigo].append(ident)
    for m in rows_m:
        if m["_fila"] < 10 or m["_fila"] > 1009 or not plain(m.get("B")):
            continue
        codigo = plain(m.get("B"))
        if len(lookup[codigo]) != 1:
            pendientes.append(f"Movimientos fila {m['_fila']}: ID histórico ambiguo/inexistente ({codigo}); no se importa.")
            continue
        tipo_map = {"Carga": "CARGA", "Transferencia": "TRANSFERENCIA", "Baja": "BAJA",
                    "Ajuste +": "AJUSTE +", "Ajuste -": "AJUSTE -"}
        tipo = tipo_map.get(plain(m.get("C")))
        cant, fm = i_num(m.get("D")), date_excel(m.get("A"))
        if not tipo or cant <= 0 or not parse_date(fm):
            pendientes.append(f"Movimientos fila {m['_fila']}: fecha, tipo o cantidad inválidos; no se importa.")
            continue
        ref = "LEG-" + digest[:8].upper() + "-" + str(m["_fila"])
        evt_id = "MOV-" + str(uuid.uuid5(NAMESPACE, digest + ":M:" + str(m["_fila"]))).replace("-", "")[:20].upper()
        nuevo = dict(zip(MOVIMIENTO, [
            evt_id, ref, fm, tipo, lookup[codigo][0], cant,
            cant if tipo == "AJUSTE +" else -cant,
            "", plain(m.get("Q")), plain(m.get("L")), plain(m.get("M")), plain(m.get("R")),
            plain(m.get("N")), "", "", "", timestamp(), batch_id, m["_fila"],
        ]))
        mov.append(nuevo)
    duplicados = {k: n for k, n in collections.Counter(r["codigo_excel"] for r in rec).items()
                  if k and n > 1}
    return {"recepciones": rec, "movimientos": mov, "pendientes": pendientes,
            "duplicados": duplicados, "importacion_id": batch_id, "hash": digest}


# ───────────────────────────── Google Sheets ─────────────────────────────
def tiene_secrets() -> bool:
    try:
        return bool(st.secrets.get("gcp_service_account"))
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def libro_google():
    if gspread is None or Credentials is None:
        raise RuntimeError("Instale gspread y google-auth para usar Google Sheets.")
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    key = st.secrets.get("SPREADSHEET_ID")
    if not key:
        raise ValueError("Falta SPREADSHEET_ID en secrets de Streamlit.")
    return gspread.authorize(creds).open_by_key(key)


@st.cache_resource(show_spinner=False)
def preparar_google():
    libro = libro_google()
    existentes = {s.title: s for s in libro.worksheets()}
    for nombre, columnas in SHEETS.items():
        if nombre not in existentes:
            ws = libro.add_worksheet(nombre, rows=4000, cols=len(columnas))
            ws.append_row(columnas, value_input_option="RAW")
        elif existentes[nombre].row_values(1) != columnas:
            raise ValueError(f"Encabezados incompatibles en {nombre}. No se modificarán automáticamente.")


@st.cache_data(ttl=20, show_spinner=False)
def leer_google() -> dict:
    archivo = libro_google()
    return {
        clase: archivo.worksheet(nombre).get_all_records(default_blank="")
        for clase, nombre in MAP_SHEET.items()
    }


def cargar_registros(fresco=False) -> dict:
    if tiene_secrets():
        if fresco:
            leer_google.clear()
        return leer_google()
    if "datos_demo" not in st.session_state:
        st.session_state["datos_demo"] = {k: [] for k in MAP_SHEET}
    return st.session_state["datos_demo"]


def guardar_filas(clase: str, filas: list[dict]):
    if not filas:
        return
    if tiene_secrets():
        ws = libro_google().worksheet(MAP_SHEET[clase])
        columnas = SHEETS[MAP_SHEET[clase]]
        # No escribir fórmulas importadas ni actualizar saldos directamente.
        for ini in range(0, len(filas), 125):
            ws.append_rows([[fila.get(c, "") for c in columnas] for fila in filas[ini:ini+125]],
                           value_input_option="RAW")
        leer_google.clear()
    else:
        cargar_registros()[clase].extend(filas)


def migrar_archivo(importacion: dict) -> dict:
    actuales = cargar_registros(fresco=True)
    res = {}
    for clase in ("recepciones", "movimientos"):
        campo = "id_recepcion" if clase == "recepciones" else "id_movimiento"
        guardados = {plain(row.get(campo)) for row in actuales[clase]}
        nuevos = [r for r in importacion[clase] if r[campo] not in guardados]
        guardar_filas(clase, nuevos)
        res[clase] = len(nuevos)
    return res


def registrar_operacion(filas: list[dict], fecha: date):
    actuales = cargar_registros(fresco=True)
    validar_movimientos(filas, actuales, fecha)
    guardar_filas("movimientos", filas)


def registrar_recepcion(fila: dict):
    registros = cargar_registros(fresco=True)
    duplicado = [r for r in registros["recepciones"] if
                 clean_lote(r.get("lote")) == clean_lote(fila.get("lote")) and
                 date_iso(r.get("fecha_postura")) == date_iso(fila.get("fecha_postura")) and
                 plain(r.get("tipo_hi")) == plain(fila.get("tipo_hi")) and
                 plain(r.get("guia_recepcion")).casefold() == plain(fila.get("guia_recepcion")).casefold()]
    if duplicado:
        raise ValueError("Ya existe una recepción del mismo lote, postura, clase y guía. Use un código de recepción distinto si corresponde a otra entrega.")
    if any(plain(r.get("id_recepcion")) == fila["id_recepcion"] for r in registros["recepciones"]):
        raise ValueError("Este ingreso ya fue registrado.")
    guardar_filas("recepciones", [fila])


# ────────────────────────────── PRESENTACIÓN ──────────────────────────────
STYLE = """
<style>
[data-testid="stAppViewContainer"]{background:#f6f8fb}
.block-container{padding-top:1.05rem;padding-bottom:4rem;max-width:1570px}
[data-testid="stSidebar"]{background:white;border-right:1px solid #e5eaf0}
[data-testid="stSidebar"] .stRadio label{font-size:.88rem}
[data-testid="stMetric"]{background:white;border:1px solid #e4eaf1;border-radius:15px;
  padding:14px 17px 15px;box-shadow:0 3px 13px rgba(22,49,72,.035)}
[data-testid="stMetricLabel"]{color:#697b8d;font-weight:600}
[data-testid="stMetricValue"]{color:#193f5a;font-weight:750;letter-spacing:-.04em}
div[data-testid="stVerticalBlockBorderWrapper"]>div{border-color:#e2e9f1;border-radius:14px}
.stButton button{border-radius:10px;min-height:2.7rem;font-weight:600}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"]{background:#df6b22;border:1px solid #df6b22;color:white}
.stButton button[kind="primary"]:hover{background:#c85c17;border-color:#c85c17}
.stTabs [data-baseweb="tab-list"]{gap:12px}
.stTabs [data-baseweb="tab"]{border-radius:8px}
h1,h2,h3{color:#1a3e59;letter-spacing:-.026em}
h1{font-size:1.65rem !important}h2{font-size:1.24rem !important}
.it-head{background:white;border:1px solid #e4eaf1;border-radius:16px;padding:20px 23px;
 display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:17px;
 border-top:4px solid #e47728}
.it-kicker{font-size:.73rem;font-weight:800;letter-spacing:.095em;color:#cf6823;text-transform:uppercase}
.it-title{font-size:1.58rem;line-height:1.22;font-weight:780;color:#173b55;letter-spacing:-.03em;margin:6px 0 5px}
.it-sub{font-size:.88rem;color:#697b8b;line-height:1.45}
.it-pill{background:#eaf4fb;color:#1e648b;border:1px solid #d6e8f3;
 border-radius:8px;font-size:.77rem;padding:7px 10px;font-weight:700;white-space:nowrap}
.it-brand{border-radius:13px;border:1px solid #e4eaf1;background:#f6f8fa;padding:13px 14px;margin-bottom:17px}
.it-brand strong{font-size:1.12rem;color:#163c58;letter-spacing:-.035em}
.it-brand span{display:block;color:#778a9b;font-size:.73rem;margin-top:3px}
.it-note{color:#75869a;font-size:.8rem;line-height:1.5}
.it-overline{font-size:.72rem;letter-spacing:.08em;font-weight:800;text-transform:uppercase;color:#6c8296}
.it-rule{border-left:3px solid #e47728;padding:7px 11px;background:#fff;border-radius:0 8px 8px 0;
 color:#576e81;font-size:.82rem}
@media(max-width:760px){.it-head{display:block;padding:16px}.it-title{font-size:1.28rem}.it-pill{display:inline-block;margin-top:10px}}
</style>
"""


def render_header(title: str, sub: str, corte: date, identificacion: str = "P.I. Pucacaca"):
    st.markdown(
        f'<div class="it-head"><div><div class="it-kicker">Control de almacén / huevos incubables</div>'
        f'<div class="it-title">{html.escape(title)}</div>'
        f'<div class="it-sub">{html.escape(sub)}</div></div>'
        f'<div class="it-pill">{html.escape(identificacion)} · Corte {corte:%d/%m/%Y}</div></div>',
        unsafe_allow_html=True,
    )


def flash(mensaje: str):
    st.session_state["flash"] = mensaje
    if tiene_secrets():
        leer_google.clear()
    st.rerun()


def csv_bytes(filas: list[dict]) -> bytes:
    return pd.DataFrame(filas).to_csv(index=False).encode("utf-8-sig")


def tabla(filas: list[dict] | pd.DataFrame, height=360):
    df = filas if isinstance(filas, pd.DataFrame) else pd.DataFrame(filas)
    if df.empty:
        st.info("No hay registros para los filtros seleccionados.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True, height=min(height, 45 + len(df)*35))


def tabla_operativa(inv: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(inv)
    if df.empty:
        return df
    campos = {
        "lote": "Lote", "fecha_postura": "Postura", "tipo_hi": "Clase",
        "edad_repro": "Edad (sem.)", "guia_recepcion": "Guía", "ubicacion": "Ubicación",
        "ingresos_hi": "Ingresos HI", "saldo_hi": "Saldo HI", "cajas": "Cajas",
        "adicionales": "Adicionales", "dias_postura": "Días desde postura",
        "dias_restantes": "Días restantes", "estado": "Prioridad",
    }
    return df[list(campos)].rename(columns=campos)


def opciones(inv: list[dict]) -> list[dict]:
    return sorted((r for r in inv if r["saldo_hi"] > 0),
                  key=lambda r: (r["dias_restantes"] if r["dias_restantes"] is not None else 9999,
                                 r["fecha_postura"], r["lote"]))


def etiqueta(r: dict) -> str:
    return f"{r['lote']} · {etiqueta_postura(r['fecha_postura'])} · {r['tipo_hi']} · {num_format(r['saldo_hi'])} HI · {r['ubicacion']}"


def selector_cantidades(inv: list[dict], clave: str) -> list[dict]:
    elegibles = opciones(inv)
    if not elegibles:
        st.warning("No existen recepciones con saldo disponible al corte seleccionado.")
        return []
    buscar_lote = st.text_input("Filtrar por lote o guía", key=f"{clave}_buscar", placeholder="Ej.: 228, SF C016, RECP...")
    clase = st.selectbox("Clase de huevo", ["Todas", "OK", "R", "RR"], key=f"{clave}_clase")
    if buscar_lote:
        elegibles = [r for r in elegibles if buscar_lote.casefold() in
                     (r["lote"] + " " + r["guia_recepcion"] + " " + r["ubicacion"]).casefold()]
    if clase != "Todas":
        elegibles = [r for r in elegibles if r["tipo_hi"] == clase]
    by_id = {r["id_recepcion"]: r for r in elegibles}
    seleccion = st.multiselect("Seleccionar recepciones (puede combinar varias)", list(by_id),
                               format_func=lambda rid: etiqueta(by_id[rid]), key=f"{clave}_sel")
    if not seleccion:
        return []
    entradas = [{"id_recepcion": rid, "Lote": by_id[rid]["lote"],
                 "Postura": by_id[rid]["fecha_postura"], "Clase": by_id[rid]["tipo_hi"],
                 "Disponible": by_id[rid]["saldo_hi"], "Cantidad HI": 0} for rid in seleccion]
    ed = st.data_editor(
        pd.DataFrame(entradas), hide_index=True, use_container_width=True,
        disabled=["id_recepcion", "Lote", "Postura", "Clase", "Disponible"],
        column_config={"Cantidad HI": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                       "id_recepcion": None}, key=f"{clave}_ed", num_rows="fixed",
    )
    items = [{"id_recepcion": r["id_recepcion"], "cantidad_hi": i_num(r["Cantidad HI"])} for r in ed.to_dict("records")]
    suma = sum(r["cantidad_hi"] for r in items)
    st.caption(f"Total seleccionado: {num_format(suma)} HI = {num_format(suma//HI_POR_CAJA)} cajas + {suma%HI_POR_CAJA} HI. Las cantidades en cero no se procesan.")
    for it in items:
        if it["cantidad_hi"] > by_id[it["id_recepcion"]]["saldo_hi"]:
            st.error(f"La cantidad supera el saldo del lote {by_id[it['id_recepcion']]['lote']}.")
    return [x for x in items if x["cantidad_hi"] > 0]


def construir_movimientos(tipo: str, items: list[dict], fecha: date, documento: str,
                           responsable: str, observacion="", incubadora="", destino="",
                           causa="", transportista="", placa="", logtag="", operacion=None) -> list[dict]:
    op = operacion or new_id("OP")
    salida = []
    for index, it in enumerate(items, 1):
        cant = it["cantidad_hi"]
        salida.append(dict(zip(MOVIMIENTO, [
            f"{op}-{index:03d}", op, fecha.isoformat(), tipo, it["id_recepcion"], cant,
            cant if tipo == "AJUSTE +" else -cant, incubadora, destino,
            documento.strip(), responsable.strip(), causa.strip(), observacion.strip(),
            transportista.strip(), placa.strip(), logtag.strip(), timestamp(), "", "",
        ])))
    return salida


def presentar_dashboard(registros, inv, corte, reglas):
    render_header("Centro de control", "Saldo disponible, prioridades de carga y movimientos del almacén de HI.", corte)
    k = estadisticas(inv, registros["movimientos"], corte)
    a,b,c,d = st.columns(4)
    a.metric("Saldo en almacén", f"{num_format(k['saldo'])} HI")
    b.metric("Cajas completas", num_format(k["cajas"]), f"+ {k['adicionales']} HI")
    c.metric("HI a priorizar", num_format(k["prioridad"]))
    d.metric("Recepciones con saldo", num_format(k["grupos"]))
    a,b,c,d = st.columns(4)
    a.metric("Ingresos acumulados", num_format(k["ingresos"]))
    b.metric("Cargados a incubación", num_format(k["cargados"]))
    c.metric("Transferidos a Tarapoto", num_format(k["transferidos"]))
    d.metric("Antigüedad ponderada", f"{k['promedio_dias']} días")
    st.caption("Los movimientos se descuentan una sola vez del almacén. Los días se cuentan desde la postura (no solo desde la llegada).")
    c1,c2 = st.columns([1.3,1])
    with c1:
        with st.container(border=True):
            st.subheader("Existencias por lote reproductora")
            df = pd.DataFrame(inv)
            if not df.empty:
                df = df.groupby("lote", as_index=False)["saldo_hi"].sum().sort_values("saldo_hi", ascending=False).head(15)
                st.bar_chart(df.set_index("lote"), y="saldo_hi", color="#1d6b96", height=310)
            else:
                st.info("Sin información de existencias.")
    with c2:
        with st.container(border=True):
            st.subheader("Composición actual")
            df = pd.DataFrame(inv)
            if not df.empty:
                series = df.groupby("tipo_hi")["saldo_hi"].sum().reindex(["OK", "R", "RR"], fill_value=0)
                st.bar_chart(series, color="#e3782b", height=310)
                st.caption("OK: incubable · R: recuperado almacén · RR: recuperado granja")
            else:
                st.info("Sin información.")
    with st.container(border=True):
        st.subheader("Prioridad de carga")
        st.markdown('<div class="it-rule">Los objetivos por edad son <b>provisionales</b>, tomados del Excel. Deben ser aprobados por el área técnica antes de utilizarlos como criterio operativo.</div>', unsafe_allow_html=True)
        foco = [r for r in opciones(inv) if r["estado"] in ("Objetivo superado", "Cargar hoy", "Próximo objetivo")]
        tabla(tabla_operativa(foco).head(30) if foco else [], height=315)
        st.caption(f"Reglas de ejemplo: <50 semanas {reglas[0]} días; 50–59 semanas {reglas[1]} días; ≥60 semanas {reglas[2]} días.")
    inc = incidencias(registros, inv)
    if inc:
        with st.expander(f"Controles documentales pendientes ({len(inc)})"):
            tabla(inc, 300)


def presentar_recepciones(registros, inv, corte):
    render_header("Recepciones de HI", "Cada recepción conserva su guía, postura, tipo de huevo y ubicación.", corte)
    t1,t2 = st.tabs(["Registrar ingreso", "Ingresos registrados"])
    with t1:
        with st.container(border=True):
            st.subheader("Nueva recepción a almacén")
            with st.form("new_reception", clear_on_submit=True):
                a,b,c = st.columns(3)
                lote = a.text_input("Lote reproductora *", placeholder="Ej.: 237 / SF C016")
                tipo = b.selectbox("Clase HI *", TIPOS_HI)
                edad = c.number_input("Edad reproductora a postura (semanas) *", min_value=1, max_value=100, value=45)
                a,b,c = st.columns(3)
                postura = a.date_input("Fecha de postura *", max_value=date.today())
                ingreso = b.date_input("Fecha de ingreso *", max_value=date.today())
                cantidad = c.number_input("Cantidad de HI *", min_value=1, step=1)
                a,b,c = st.columns(3)
                ubicacion = a.text_input("Almacén / posición *", placeholder="Ej.: REFFER 2")
                guia = b.text_input("Guía / código de recepción *", placeholder="Ej.: RECP-02-05-11")
                origen = c.selectbox("Origen *", ORIGENES)
                responsable = st.text_input("Responsable *", value=st.session_state.get("operador", ""))
                observ = st.text_area("Observaciones / condición", height=85)
                aceptar = st.checkbox("Confirmo que la información coincide con la recepción física")
                guardar = st.form_submit_button("Registrar recepción", type="primary", use_container_width=True)
            if guardar:
                try:
                    if not all((lote.strip(), guia.strip(), ubicacion.strip(), responsable.strip())):
                        raise ValueError("Complete lote, guía, ubicación y responsable.")
                    if ingreso < postura:
                        raise ValueError("La fecha de ingreso no puede ser anterior a la postura.")
                    if not aceptar:
                        raise ValueError("Confirme la verificación de la recepción antes de guardarla.")
                    fila = dict(zip(RECEPCION, [new_id("REC"), clean_lote(lote),
                         postura.isoformat(), int(edad), tipo, ingreso.isoformat(), int(cantidad),
                         ubicacion.strip(), guia.strip(), origen, responsable.strip(), observ.strip(),
                         "", "", timestamp(), ""]))
                    registrar_recepcion(fila)
                    flash("Recepción de HI guardada correctamente.")
                except Exception as exc:
                    st.error(str(exc))
    with t2:
        registros_ = registros["recepciones"]
        tabla([{"Fecha ingreso": x.get("fecha_ingreso", ""), "Lote": clean_lote(x.get("lote")),
                "Postura": x.get("fecha_postura", ""), "Clase": x.get("tipo_hi", ""),
                "Cantidad HI": i_num(x.get("cantidad_hi")), "Ubicación": x.get("ubicacion", ""),
                "Guía": x.get("guia_recepcion", ""), "Responsable": x.get("responsable", ""),
                "ID": x.get("id_recepcion", "")} for x in registros_], 470)
        st.download_button("Exportar ingresos (CSV)", csv_bytes(registros_), file_name="HI_Pucacaca_Ingresos.csv", mime="text/csv")


def presentar_existencias(registros, inv, corte):
    render_header("Existencias y saldos", "Consulta por recepción, lote, fecha de postura y clase OK / R / RR.", corte)
    c1,c2,c3 = st.columns(3)
    lotes = sorted({r["lote"] for r in inv})
    lote = c1.selectbox("Lote reproductora", ["Todos"]+lotes, key="filter_lot")
    tipo = c2.selectbox("Clase HI", ["Todas", *TIPOS_HI], key="filter_class")
    solo = c3.toggle("Solo saldos positivos", value=True)
    datos = [r for r in inv if (lote == "Todos" or r["lote"] == lote) and
             (tipo == "Todas" or r["tipo_hi"] == tipo) and (not solo or r["saldo_hi"] > 0)]
    t1,t2,t3 = st.tabs(["Por recepción", "Por lote", "Por postura"])
    with t1:
        tabla(tabla_operativa(sorted(datos, key=lambda r:(r["dias_restantes"] if r["dias_restantes"] is not None else 999,
                                                             r["fecha_postura"]))), 560)
    with t2:
        if datos:
            df = pd.DataFrame(datos)
            agg = df.pivot_table(index="lote", columns="tipo_hi", values="saldo_hi", aggfunc="sum", fill_value=0)
            agg = agg.reindex(columns=list(TIPOS_HI), fill_value=0)
            agg["TOTAL HI"] = agg.sum(axis=1)
            agg["Cajas"] = agg["TOTAL HI"].clip(lower=0) // HI_POR_CAJA
            agg["Adicionales"] = agg["TOTAL HI"].clip(lower=0) % HI_POR_CAJA
            tabla(agg.reset_index().rename(columns={"lote":"Lote"}).sort_values("TOTAL HI", ascending=False), 470)
        else: st.info("Sin datos.")
    with t3:
        if datos:
            df = pd.DataFrame(datos)
            agg = df.pivot_table(index=["lote", "fecha_postura"], columns="tipo_hi", values="saldo_hi", aggfunc="sum", fill_value=0)
            agg = agg.reindex(columns=list(TIPOS_HI), fill_value=0)
            agg["TOTAL HI"] = agg.sum(axis=1)
            tabla(agg.reset_index().rename(columns={"lote":"Lote", "fecha_postura":"Postura"}), 470)
        else: st.info("Sin datos.")
    st.download_button("Exportar existencias filtradas (CSV)", csv_bytes(datos), file_name="HI_Pucacaca_Existencias.csv", mime="text/csv")
    st.caption("Las cajas equivalentes de cada recepción se calculan individualmente; al consolidar se convierten los HI totales a cajas de 360, sin redondear remanentes por separado.")


def presentar_cargas(registros, inv, corte):
    render_header("Carga por incubadora", "Consumo de almacén por máquina, documento y recepciones de origen.", corte)
    st.info("Una carga puede usar varias recepciones. Todas quedan vinculadas a una misma operación y a una incubadora. No registre aquí el traslado posterior a nacedora.")
    hoy = date.today()
    f = st.date_input("Fecha operativa de carga", value=hoy, max_value=hoy, key="fecha_carga")
    inventario_fecha = inventario(registros["recepciones"], registros["movimientos"], f)
    items = selector_cantidades(inventario_fecha, "cargas")
    a,b,c = st.columns(3)
    maquina = a.text_input("Incubadora *", placeholder="Ej.: INC-01")
    doc = b.text_input("Orden / documento de carga *", placeholder="Ej.: CARG-2026-001")
    resp = c.text_input("Responsable *", value=st.session_state.get("operador", ""), key="carga_resp")
    obs = st.text_area("Observaciones de la carga", key="carga_obs", height=75)
    confirmado = st.checkbox("Verifiqué máquina, documento, cantidades y saldos", key="carga_confirm")
    suma = sum(x["cantidad_hi"] for x in items)
    if st.button(f"Confirmar carga de {num_format(suma)} HI", type="primary", disabled=suma<=0, use_container_width=True):
        try:
            if not confirmado: raise ValueError("Marque la confirmación operativa.")
            if not all((maquina.strip(), doc.strip(), resp.strip())):
                raise ValueError("Incubadora, documento y responsable son obligatorios.")
            draft = st.session_state.setdefault("draft_operacion_carga", new_id("OP"))
            filas = construir_movimientos("CARGA", items, f, doc, resp, obs, incubadora=maquina, operacion=draft)
            registrar_operacion(filas, f)
            st.session_state.pop("draft_operacion_carga", None)
            flash(f"Carga confirmada: {num_format(suma)} HI en {maquina}.")
        except Exception as exc: st.error(str(exc))
    st.divider()
    st.subheader("Cargas registradas por incubadora")
    cargos = [m for m in registros["movimientos"] if plain(m.get("tipo")) == "CARGA"]
    if cargos:
        df = pd.DataFrame(cargos)
        df["incubadora"] = df["incubadora"].replace("", "Sin identificar (histórico)")
        agrupado = df.groupby(["fecha_movimiento", "incubadora", "documento"], as_index=False)["cantidad_hi"].agg(lambda col: sum(i_num(x) for x in col))
        tabla(agrupado.rename(columns={"fecha_movimiento":"Fecha", "incubadora":"Incubadora", "documento":"Documento", "cantidad_hi":"HI cargados"}), 360)
    else: st.info("Sin cargas registradas.")


def presentar_transferencias(registros, inv, corte):
    render_header("Transferencias a Tarapoto", "Salidas documentadas de Pucacaca. La recepción en destino se confirma por separado.", corte)
    hoy = date.today()
    f = st.date_input("Fecha de despacho", value=hoy, max_value=hoy, key="f_transf")
    inv_fecha = inventario(registros["recepciones"], registros["movimientos"], f)
    items = selector_cantidades(inv_fecha, "transferencia")
    a,b,c = st.columns(3)
    st.text_input("Planta destino", value=DESTINO, disabled=True)
    documento = a.text_input("Guía de remisión *", key="tr_documento")
    responsable = b.text_input("Responsable despacho *", value=st.session_state.get("operador", ""), key="tr_responsable")
    transportista = c.text_input("Transportista / conductor", key="tr_transportista")
    a,b = st.columns(2)
    placa = a.text_input("Placa de vehículo", key="tr_placa")
    logtag = b.text_input("Código LogTag / registrador", key="tr_logtag")
    obs = st.text_area("Observación de traslado", key="tr_obs", height=70)
    confirmar = st.checkbox("Confirmo las cantidades entregadas al transporte", key="tr_ok")
    suma = sum(x["cantidad_hi"] for x in items)
    if st.button(f"Despachar {num_format(suma)} HI a Tarapoto", type="primary", disabled=suma<=0, use_container_width=True):
        try:
            if not confirmar: raise ValueError("Confirme la entrega física al transporte.")
            if not documento.strip() or not responsable.strip():
                raise ValueError("Guía de remisión y responsable son obligatorios.")
            draft = st.session_state.setdefault("draft_operacion_transf", new_id("OP"))
            filas = construir_movimientos("TRANSFERENCIA", items, f, documento, responsable, obs,
                                          destino=DESTINO, transportista=transportista, placa=placa, logtag=logtag,
                                          operacion=draft)
            registrar_operacion(filas, f)
            st.session_state.pop("draft_operacion_transf", None)
            flash(f"Transferencia despachada: {num_format(suma)} HI a P.I. Tarapoto.")
        except Exception as exc: st.error(str(exc))
    st.divider()
    st.subheader("Despachos y confirmaciones en Tarapoto")
    transfers = [m for m in registros["movimientos"] if plain(m.get("tipo")) == "TRANSFERENCIA"]
    groups = collections.defaultdict(list)
    for m in transfers: groups[plain(m.get("id_operacion"))].append(m)
    confs = collections.defaultdict(list)
    for c in registros["confirmaciones"]: confs[plain(c.get("id_operacion"))].append(c)
    vista = []
    for id_op, rows in groups.items():
        total = sum(i_num(r.get("cantidad_hi")) for r in rows)
        aceptados = sum(i_num(c.get("recibidos_hi")) for c in confs[id_op])
        rechazados = sum(i_num(c.get("rechazados_hi")) for c in confs[id_op])
        faltantes = sum(i_num(c.get("faltantes_hi")) for c in confs[id_op])
        conciliado = aceptados + rechazados + faltantes
        vista.append({"ID operación":id_op, "Fecha":rows[0].get("fecha_movimiento", ""),
            "Guía":rows[0].get("documento", ""), "Despachados HI":total,
            "Recibidos HI":aceptados, "Rechazados HI":rechazados, "Faltantes HI":faltantes,
            "Por conciliar":total-conciliado, "Estado":"Conciliado" if conciliado == total else "Pendiente"})
    tabla(vista, 350)
    if groups:
        with st.expander("Confirmar llegada informada por Tarapoto"):
            opciones_ops = [v["ID operación"] for v in vista if v["Por conciliar"] > 0]
            if opciones_ops:
                op = st.selectbox("Despacho pendiente", opciones_ops,
                                  format_func=lambda x: f"{x} · {next(v['Guía'] for v in vista if v['ID operación']==x)}")
                pendiente = next(v["Por conciliar"] for v in vista if v["ID operación"] == op)
                with st.form("confirmacion_tar"):
                    fecha = st.date_input("Fecha de recepción informada", value=date.today(), max_value=date.today())
                    a,b,c = st.columns(3)
                    recibidos = a.number_input("HI conformes", min_value=0, max_value=pendiente, value=pendiente)
                    rechazados = b.number_input("HI rechazados", min_value=0, max_value=pendiente, value=0)
                    faltantes = c.number_input("HI faltantes", min_value=0, max_value=pendiente, value=0)
                    documento = st.text_input("Documento de recepción *")
                    responsable = st.text_input("Responsable que confirma *", value=st.session_state.get("operador", ""))
                    obs = st.text_area("Observaciones", height=65)
                    submit = st.form_submit_button("Registrar confirmación de destino", type="primary")
                if submit:
                    try:
                        if sum([recibidos,rechazados,faltantes]) <= 0 or sum([recibidos,rechazados,faltantes]) > pendiente:
                            raise ValueError("Las cantidades deben conciliarse sin superar lo pendiente.")
                        if not documento.strip() or not responsable.strip():
                            raise ValueError("Documento y responsable obligatorios.")
                        fresh = cargar_registros(fresco=True)
                        all_sent = sum(i_num(m.get("cantidad_hi")) for m in fresh["movimientos"] if m.get("id_operacion") == op)
                        all_confirmed = sum(i_num(x.get("recibidos_hi"))+i_num(x.get("rechazados_hi"))+i_num(x.get("faltantes_hi"))
                                            for x in fresh["confirmaciones"] if x.get("id_operacion") == op)
                        if sum([recibidos,rechazados,faltantes]) > all_sent - all_confirmed:
                            raise ValueError("Otro usuario modificó el despacho; actualice la pantalla.")
                        fila = dict(zip(CONFIRMACION, [new_id("CONF"), op, fecha.isoformat(),
                              recibidos, rechazados, faltantes, documento.strip(), responsable.strip(), obs.strip(), timestamp()]))
                        guardar_filas("confirmaciones", [fila]); flash("Confirmación de llegada registrada.")
                    except Exception as exc: st.error(str(exc))
            else: st.success("Todos los despachos están conciliados.")
        st.caption("La confirmación en Tarapoto es un control documental de llegada; NO suma stock a Pucacaca.")


def presentar_ajustes(registros, inv, corte):
    render_header("Bajas y ajustes", "Correcciones justificadas mediante movimientos trazables; nunca se edita el saldo manualmente.", corte)
    tipo = st.selectbox("Operación", ["BAJA", "AJUSTE +", "AJUSTE -"])
    f = st.date_input("Fecha de la operación", value=date.today(), max_value=date.today())
    inv_fecha = inventario(registros["recepciones"], registros["movimientos"], f)
    lista = inv_fecha if tipo == "AJUSTE +" else opciones(inv_fecha)
    if not lista:
        st.warning("No existen recepciones para operar.")
        return
    by_id = {r["id_recepcion"]: r for r in lista}
    rid = st.selectbox("Recepción", list(by_id), format_func=lambda x: etiqueta(by_id[x]))
    cantidad = st.number_input("Cantidad HI", min_value=1, step=1)
    a,b = st.columns(2)
    causa = a.selectbox("Causa / motivo *", ["Rotura", "Contaminación", "Diferencia inventario", "Error documental", "Otro"])
    doc = b.text_input("Documento / acta *")
    responsable = st.text_input("Responsable *", value=st.session_state.get("operador", ""), key="aj_responsable")
    obs = st.text_area("Explicación detallada *", height=85)
    confirmar = st.checkbox("Confirmo que la corrección cuenta con sustento documental")
    if st.button("Registrar movimiento de ajuste", type="primary"):
        try:
            if not confirmar or not doc.strip() or not obs.strip() or not responsable.strip():
                raise ValueError("Documento, responsable, explicación y confirmación son obligatorios.")
            draft = st.session_state.setdefault("draft_operacion_ajuste", new_id("OP"))
            rows = construir_movimientos(tipo, [{"id_recepcion":rid, "cantidad_hi":int(cantidad)}], f, doc, responsable, obs, causa=causa, operacion=draft)
            registrar_operacion(rows, f)
            st.session_state.pop("draft_operacion_ajuste", None)
            flash("Movimiento de ajuste registrado y vinculado a la recepción.")
        except Exception as exc: st.error(str(exc))


def presentar_conciliacion(registros, inv, corte):
    render_header("Conciliación física", "Contrasta el conteo físico con el saldo del sistema, sin ajustar automáticamente las existencias.", corte)
    disponibles = opciones(inv)
    if not disponibles:
        st.info("No existen recepciones con saldo disponible.")
        return
    by_id = {r["id_recepcion"]:r for r in disponibles}
    rid = st.selectbox("Recepción que se contó", list(by_id), format_func=lambda x: etiqueta(by_id[x]))
    saldo = by_id[rid]["saldo_hi"]
    a,b,c = st.columns(3)
    a.metric("Saldo del sistema", num_format(saldo))
    fecha = b.date_input("Fecha del conteo", value=corte, max_value=date.today())
    fisico = c.number_input("Conteo físico HI", min_value=0, value=saldo, step=1)
    diferencia = int(fisico) - saldo
    if diferencia == 0: st.success("Conteo conforme: sin diferencias.")
    else: st.warning(f"Diferencia: {diferencia:+,} HI. Esta conciliación NO modifica el stock.")
    with st.form("conteo"):
        documento = st.text_input("Acta / documento de conteo *")
        responsable = st.text_input("Responsable del conteo *", value=st.session_state.get("operador", ""))
        observ = st.text_area("Hallazgos / explicación", height=70)
        confirmado = st.checkbox("Confirmo que el conteo fue efectuado físicamente")
        ok = st.form_submit_button("Guardar acta de conteo", type="primary")
    if ok:
        try:
            if not confirmado or not documento.strip() or not responsable.strip():
                raise ValueError("Documento, responsable y confirmación son obligatorios.")
            if fecha != corte:
                raise ValueError("Seleccione el mismo día como fecha de corte y conteo para evitar comparaciones incorrectas.")
            frescos = cargar_registros(fresco=True)
            saldo_fresco = {x["id_recepcion"]:x["saldo_hi"] for x in inventario(frescos["recepciones"], frescos["movimientos"], corte)}.get(rid)
            if saldo_fresco != saldo:
                raise ValueError("El saldo cambió desde el inicio del conteo; refresque y repita la conciliación.")
            fila = dict(zip(CONTEO, [new_id("CNT"), fecha.isoformat(), rid, saldo, int(fisico), diferencia,
                                         documento.strip(), responsable.strip(), observ.strip(), timestamp()]))
            guardar_filas("conteos", [fila]); flash("Acta de conciliación registrada. No se alteró el saldo contable.")
        except Exception as exc: st.error(str(exc))
    st.divider()
    st.subheader("Últimos conteos")
    tabla(registros["conteos"][-40:][::-1], 360)
    st.caption("Para regularizar una diferencia autorizada, ingrese posteriormente a Bajas y ajustes con su acta de sustento.")


def presentar_historial(registros, inv, corte):
    render_header("Trazabilidad y auditoría", "Reconstruye la historia de cada recepción y todos los cambios del inventario.", corte)
    tab1,tab2,tab3 = st.tabs(["Expediente de recepción", "Libro de movimientos", "Alertas de integridad"])
    with tab1:
        if not inv:
            st.info("Aún no existen recepciones.")
        else:
            by_id = {r["id_recepcion"]: r for r in inv}
            rid = st.selectbox("Seleccione una recepción", list(by_id), format_func=lambda x: etiqueta(by_id[x]))
            r = by_id[rid]
            a,b,c,d = st.columns(4)
            a.metric("Saldo HI",num_format(r["saldo_hi"]))
            b.metric("Ingreso HI",num_format(r["ingresos_hi"]))
            c.metric("Lote",r["lote"])
            d.metric("Tipo",r["tipo_hi"])
            st.caption(f"ID interno: {rid}  ·  Guía: {r['guia_recepcion']}  ·  Ubicación: {r['ubicacion']}  ·  Postura: {r['fecha_postura']}")
            m = [x for x in registros["movimientos"] if plain(x.get("id_recepcion")) == rid]
            origen = [{"Fecha":r["fecha_ingreso"], "Movimiento":"INGRESO", "Documento":r["guia_recepcion"],
                       "Incubadora":"", "Variación HI":r["ingresos_hi"], "Responsable":r["responsable"]}]
            origen.extend({"Fecha":x.get("fecha_movimiento", ""), "Movimiento":x.get("tipo", ""),
                           "Documento":x.get("documento", ""), "Incubadora":x.get("incubadora", ""),
                           "Variación HI":i_num(x.get("variacion_hi")), "Responsable":x.get("responsable", "")} for x in m)
            tabla(sorted(origen, key=lambda x:x["Fecha"]), 380)
    with tab2:
        tipo = st.selectbox("Filtrar movimiento", ["Todos", *TIPOS_MOV])
        ms = [x for x in registros["movimientos"] if tipo == "Todos" or x.get("tipo") == tipo]
        tabla(ms[::-1], 520)
        st.download_button("Exportar libro de movimientos (CSV)", csv_bytes(ms),
                           file_name="HI_Pucacaca_Movimientos.csv", mime="text/csv")
    with tab3:
        alertas = incidencias(registros, inv)
        if not alertas: st.success("No se detectaron incidencias en los controles automáticos disponibles.")
        else: tabla(alertas, 460)
        st.caption("Los códigos de recepción duplicados en el Excel se mantienen por separado; las cargas históricas sin incubadora no se completan artificialmente.")


def presentar_importacion(registros, inv, corte, reglas):
    render_header("Importación y parámetros", "Previsualiza el Excel recibido y migra únicamente a hojas nuevas, sin alterar los datos originales.", corte)
    t1,t2,t3 = st.tabs(["Importar Excel", "Reglas del control", "Estado de conexión"])
    with t1:
        st.markdown("**Compatible con las hojas `Existencias` y `Movimientos` del archivo recibido.** Conserva las clases OK/R/RR, sus cantidades y sus guías.")
        f = st.file_uploader("Seleccionar Control Almacen de HI DonPollo.xlsx", type=["xlsx"], key="excel_ingreso")
        if f is not None:
            try:
                contenido = f.getvalue()
                if len(contenido) > 12_000_000:
                    raise ValueError("Archivo demasiado grande (>12 MB) para esta importación.")
                parsed = preparar_importacion_excel(contenido)
                r,m = parsed["recepciones"],parsed["movimientos"]
                a,b,c,d = st.columns(4)
                a.metric("Recepciones a evaluar", len(r));b.metric("Movimientos a evaluar",len(m))
                c.metric("HI ingresados",num_format(sum(x["cantidad_hi"] for x in r)))
                d.metric("HI movimientos",num_format(sum(x["cantidad_hi"] for x in m)))
                st.caption(f"Identificador de archivo: {parsed['importacion_id']}")
                for codigo,n in parsed["duplicados"].items():
                    st.warning(f"Código histórico duplicado {codigo}: {n} recepciones. Se crearán IDs internos individuales; no se fusionarán cantidades.")
                for nota in parsed["pendientes"][:25]: st.error(nota)
                if len(parsed["pendientes"])>25: st.warning("Existen más incidencias; revisar el archivo.")
                saldo_calc = sum(x["cantidad_hi"] for x in r) + sum(x["variacion_hi"] for x in m)
                st.info(f"Saldo proyectado con este archivo, antes de sumar operaciones posteriores: {num_format(saldo_calc)} HI.")
                with st.expander("Ver muestra de recepciones"):
                    tabla(r[:12], 400)
                actuales_ids = {plain(x.get("id_recepcion")) for x in registros["recepciones"]}
                faltan = sum(x["id_recepcion"] not in actuales_ids for x in r)
                st.caption(f"Recepciones nuevas en destino: {faltan}. La importación es reintentable y no duplica las filas del mismo archivo.")
                st.warning("Si ya hay movimientos en el sistema, antes de importar un saldo histórico adicional confirme que no representan las mismas existencias.")
                confirmar = st.checkbox("Confirmo que validé el corte y que este archivo no duplica inventario ya registrado", key="confirmar_import")
                if st.button("Importar después de verificar", type="primary", disabled=not confirmar):
                    resultado = migrar_archivo(parsed)
                    flash(f"Importación terminada: {resultado['recepciones']} recepciones y {resultado['movimientos']} movimientos nuevos.")
            except Exception as exc:
                st.error(f"No se pudo preparar o importar el Excel: {exc}")
        else:
            st.info("Sube el archivo Excel para revisar sus datos y comenzar una prueba en modo demostración, o importarlo a las hojas nuevas de Google Sheets.")
    with t2:
        st.subheader("Parámetros que deben validar Operaciones e Incubación")
        st.markdown(f"- Huevos por caja: **{HI_POR_CAJA} HI** (según el Excel).  ")
        st.markdown(f"- Reproductoras menores de 50 semanas: **{reglas[0]} días**.  ")
        st.markdown(f"- Reproductoras de 50–59 semanas: **{reglas[1]} días**.  ")
        st.markdown(f"- Reproductoras desde 60 semanas: **{reglas[2]} días**.  ")
        st.warning("Estas referencias de almacenamiento son ejemplos del Excel: no representan estándares aprobados. Pueden ajustarse desde el menú lateral para análisis exploratorio.")
        st.caption("Fecha de postura = día 0. La antigüedad incluye tiempo en granja, transporte y planta. El saldo se calcula al corte seleccionado.")
    with t3:
        st.metric("Modo de persistencia", "Google Sheets" if tiene_secrets() else "Demo temporal")
        if tiene_secrets():
            st.success("Las nuevas operaciones se guardan en hojas separadas de Google Sheets.")
        else:
            st.warning("Sin credenciales: los registros de esta sesión solo viven en la memoria de la aplicación. Se perderán al reiniciar o cerrar la sesión.")
        tabla([{"Hoja nueva":k, "N.º de campos":len(v)} for k,v in SHEETS.items()], 250)
        st.caption("Las hojas anteriores `lotes`, `movimientos` y las hojas `traz_*` de IncubaTrack 2.0 no se modifican.")
        st.error("Límite operativo: Google Sheets no ofrece transacciones ni bloqueo concurrente. Para alta concurrencia se requiere base de datos transaccional y autenticación por usuario.")


def main():
    st.set_page_config(page_title="IncubaTrack | Almacén HI Pucacaca", page_icon="🥚", layout="wide", initial_sidebar_state="expanded")
    st.markdown(STYLE, unsafe_allow_html=True)
    if tiene_secrets():
        try:
            preparar_google()
        except Exception as exc:
            st.error(f"No se pudo acceder al archivo Google Sheets: {exc}")
            st.stop()
    with st.sidebar:
        st.markdown('<div class="it-brand"><strong>INCUBATRACK <span style="color:#df6b22;display:inline;font-size:1rem">HI</span></strong><span>P.I. Pucacaca · Gestión de almacén</span></div>',unsafe_allow_html=True)
        if tiene_secrets():
            st.caption("Datos persistentes · Google Sheets")
        else:
            st.warning("Modo demo · sin almacenamiento permanente", icon="⚠️")
        st.markdown('<span class="it-overline">Navegación</span>', unsafe_allow_html=True)
        paginas = ["Centro de control", "Recepciones HI", "Existencias y saldos", "Carga por incubadora",
                    "Transferencias a Tarapoto", "Bajas y ajustes", "Conciliación física",
                    "Trazabilidad y auditoría", "Importar Excel y parámetros"]
        pagina = st.radio("Páginas", paginas, label_visibility="collapsed")
        st.divider()
        st.markdown('<span class="it-overline">Contexto de análisis</span>',unsafe_allow_html=True)
        corte = st.date_input("Fecha de corte", value=date.today(), max_value=date.today(), key="corte_global")
        operador = st.text_input("Operador / responsable", key="operador", placeholder="Nombre para prellenar registros")
        with st.expander("Objetivos (provisionales)"):
            dias1 = st.number_input("<50 semanas (días)", min_value=1, max_value=30, value=7, key="d_7")
            dias2 = st.number_input("50–59 semanas (días)", min_value=1, max_value=30, value=5, key="d_5")
            dias3 = st.number_input("≥60 semanas (días)", min_value=1, max_value=30, value=3, key="d_3")
        st.markdown('<div class="it-note">Fuente: movimientos y recepciones. Un único saldo calculado, sin ediciones directas.<br>Control de Gestión · Don Pollo</div>', unsafe_allow_html=True)
    try:
        registros = cargar_registros()
        reglas = (int(dias1),int(dias2),int(dias3))
        inv = inventario(registros["recepciones"],registros["movimientos"],corte,reglas)
        if st.session_state.get("flash"):
            st.toast(st.session_state.pop("flash"))
        if pagina == paginas[0]: presentar_dashboard(registros, inv, corte, reglas)
        elif pagina == paginas[1]: presentar_recepciones(registros, inv, corte)
        elif pagina == paginas[2]: presentar_existencias(registros, inv, corte)
        elif pagina == paginas[3]: presentar_cargas(registros, inv, corte)
        elif pagina == paginas[4]: presentar_transferencias(registros, inv, corte)
        elif pagina == paginas[5]: presentar_ajustes(registros, inv, corte)
        elif pagina == paginas[6]: presentar_conciliacion(registros, inv, corte)
        elif pagina == paginas[7]: presentar_historial(registros, inv, corte)
        else: presentar_importacion(registros, inv, corte, reglas)
    except Exception as exc:
        st.error(f"No fue posible cargar la operación: {exc}")
        st.exception(exc)
    st.markdown('<p class="it-note" style="margin-top:26px;text-align:center">IncubaTrack · Inventario HI · P.I. Pucacaca · Control de Gestión</p>',unsafe_allow_html=True)


if __name__ == "__main__":
    main()
