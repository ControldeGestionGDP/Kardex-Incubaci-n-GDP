"""IncubaTrack Regional 4.1 | Don Pollo

Streamlit + un Google Sheets para Tarapoto, Pucacaca y Loreto.
No utiliza SQL. No sobrescribe hojas antiguas: crea IT4_*.

Integridad: movimientos inmutables, saldo derivado del kardex, escritura multihoja
mediante Google Sheets spreadsheets.batchUpdate (appendCells), IDs idempotentes.
LÍMITE: Sheets no ofrece bloqueo transaccional de stock entre operadores; para
uso concurrente coordinar las cargas y hacer conciliaciones periódicas.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
import hashlib
import html
import io
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

TZ = ZoneInfo("America/Lima")
SHEET_ID_DEFAULT = "13nw5vYfEFnP3RjHXK7CC7124-MDKCe-iAwfycvTUeS0"
PLANTAS = {"TAR": "Tarapoto", "PUC": "Pucacaca", "LOR": "Loreto"}
TIPOS_HI = ("OK", "R", "RR")
HI_CAJA = 360
NS = uuid.UUID("e812b4ba-3c87-4ca5-a687-507555714918")

TABLAS = {
    "plantas": ("IT4_Plantas", ["id_planta", "nombre", "activo"]),
    "almacenes": ("IT4_Almacenes", ["id_almacen", "id_planta", "nombre", "activo", "creado_en"]),
    "maquinas": ("IT4_Maquinas", ["id_maquina", "id_planta", "nombre", "activo", "creado_en"]),
    "partidas": ("IT4_Partidas", ["id_partida", "planta", "almacen", "ubicacion", "lote", "granja", "procedencia",
        "tipo_hi", "fecha_postura", "edad_repro", "fecha_ingreso", "cantidad_inicial", "documento", "responsable",
        "observacion", "origen", "id_partida_padre", "id_transferencia", "id_linea_transferencia",
        "codigo_excel", "fila_excel", "importacion_id", "creado_en"]),
    "movimientos": ("IT4_Movimientos", ["id_movimiento", "id_operacion", "fecha_movimiento", "planta", "almacen",
        "id_partida", "tipo", "cantidad", "variacion", "id_maquina", "id_transferencia", "documento", "responsable",
        "causa", "observacion", "importacion_id", "creado_en"]),
    "transferencias": ("IT4_Transferencias", ["id_transferencia", "fecha_despacho", "planta_origen", "almacen_origen",
        "planta_destino", "almacen_destino", "documento", "responsable", "transportista", "placa", "logtag", "observacion", "creado_en"]),
    "lineas": ("IT4_Transfer_Detalle", ["id_linea", "id_transferencia", "id_partida_origen", "cantidad_enviada", "creado_en"]),
    "confirmaciones": ("IT4_Transfer_Recepciones", ["id_confirmacion", "id_transferencia", "id_linea", "fecha_recepcion",
        "cantidad_conforme", "cantidad_rechazada", "cantidad_faltante", "id_partida_destino", "documento", "responsable",
        "observacion", "creado_en"]),
    "conteos": ("IT4_Conteos", ["id_conteo", "fecha_conteo", "id_partida", "saldo_sistema", "conteo_fisico",
        "diferencia", "documento", "responsable", "observacion", "creado_en"]),
    "parametros": ("IT4_Parametros", ["id_parametro", "planta", "clave", "valor", "responsable", "creado_en"]),
}


def now():
    return datetime.now(TZ)


def stamp():
    return now().isoformat(timespec="seconds")


def uid(prefix):
    return f"{prefix}-{now():%y%m%d}-{uuid.uuid4().hex[:12].upper()}"


def txt(value):
    return str(value if value is not None else "").strip()


def number(value, default=0):
    """Lee conteos enteros aun si Sheets usa separadores regionales de miles."""
    try:
        s = txt(value).replace("\u00a0", "").replace(" ", "")
        if not s:
            return default
        if re.fullmatch(r"[+-]?\d{1,3}(?:[.,]\d{3})+", s):
            s = s.replace(".", "").replace(",", "")
        elif re.fullmatch(r"[+-]?\d+[.,]0+", s):
            s = re.split(r"[.,]", s)[0]
        v = float(s)
        return int(v) if v.is_integer() else default
    except (ValueError, TypeError, OverflowError):
        return default


def fmt(n):
    return f"{int(n):,}".replace(",", " ")


def parse_date(v):
    try:
        return date.fromisoformat(txt(v)[:10])
    except (ValueError, TypeError):
        return None


def parse_dt(v):
    try:
        return datetime.fromisoformat(txt(v)).replace(tzinfo=None)
    except ValueError:
        d = parse_date(v)
        return datetime.combine(d, dt_time()) if d else None


def source_id(v):
    s = txt(v).upper()
    return str(int(float(s))) if re.fullmatch(r"\d+(?:\.0+)?", s) else s


def epoch_excel(v, preserve_time=False):
    if isinstance(v, (int, float)):
        d = datetime(1899, 12, 30) + timedelta(days=float(v))
        return d.isoformat(timespec="seconds") if preserve_time and d.time() != dt_time() else d.date().isoformat()
    if isinstance(v, str):
        d = parse_dt(v)
        if d:
            return d.isoformat(timespec="seconds") if preserve_time and d.time() != dt_time() else d.date().isoformat()
        for form in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(v.strip(), form).date().isoformat()
            except ValueError:
                pass
    return ""


def label_partida(r):
    return f"{r['lote']} · {r['tipo_hi']} · {r['fecha_postura'][:16]} · {fmt(r['saldo'])} HI · {r['id_partida'][-8:]}"


def fields(kind, values):
    cols = TABLAS[kind][1]
    return {c: values.get(c, "") for c in cols}


def blank():
    return {k: [] for k in TABLAS}


def excel_xlsx_rows(content, sheet_name):
    """Lee valores cacheados del Excel histórico sin macros/ejecución de fórmulas."""
    xmlns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        root = ET.fromstring(z.read("xl/workbook.xml"))
        relroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {x.attrib["Id"]: x.attrib["Target"] for x in relroot}
        sheet = next((x for x in root.iter(f"{{{xmlns}}}sheet") if x.get("name") == sheet_name), None)
        if sheet is None:
            raise ValueError(f"El Excel no contiene la hoja '{sheet_name}'.")
        target = targets[sheet.attrib[f"{{{relns}}}id"]]
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if ".." in path.split("/") or path not in z.namelist():
            raise ValueError("Ruta XLSX no válida.")
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            sr = ET.fromstring(z.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in el.iter(f"{{{xmlns}}}t")) for el in sr.findall(f"{{{xmlns}}}si")]
        out = []
        for row in ET.fromstring(z.read(path)).findall(f".//{{{xmlns}}}sheetData/{{{xmlns}}}row"):
            d = {"_fila": int(row.get("r", 0))}
            for c in row.findall(f"{{{xmlns}}}c"):
                m = re.match(r"[A-Z]+", c.get("r", ""))
                if not m:
                    continue
                v = c.find(f"{{{xmlns}}}v")
                raw = v.text if v is not None else None
                if c.get("t") == "s" and raw is not None:
                    raw = strings[int(raw)]
                elif c.get("t") == "inlineStr":
                    raw = "".join(t.text or "" for t in c.iter(f"{{{xmlns}}}t"))
                elif raw is not None and c.get("t") not in ("str", "e", "b"):
                    try:
                        raw = float(raw)
                    except ValueError:
                        pass
                d[m.group()] = raw
            out.append(d)
        return out


def import_excel_plan(blob):
    """Importa SOLO el diseño de Excel validado de Pucacaca."""
    digest = hashlib.sha256(blob).hexdigest()
    batch = "XLSX-" + digest[:18].upper()
    rr, mm = excel_xlsx_rows(blob, "Existencias"), excel_xlsx_rows(blob, "Movimientos")
    parts, moves, issues = [], [], []
    code_map = defaultdict(list)
    for r in rr:
        if not 10 <= r["_fila"] <= 439 or not source_id(r.get("B")):
            continue
        qty, kind = number(r.get("G")), txt(r.get("E")).upper()
        date_in, posture = epoch_excel(r.get("F")), epoch_excel(r.get("C"), True)
        if qty <= 0 or kind not in TIPOS_HI or not parse_date(date_in) or not parse_dt(posture):
            issues.append(f"Existencias, fila {r['_fila']}: datos mínimos no válidos")
            continue
        pid = "PART-" + uuid.uuid5(NS, digest + ":P:" + str(r["_fila"])).hex[:20].upper()
        doc = txt(r.get("I"))
        part = fields("partidas", {
            "id_partida": pid, "planta": "PUC", "almacen": "ALM-PUC", "ubicacion": txt(r.get("H")),
            "lote": source_id(r.get("B")), "granja": "", "procedencia": txt(r.get("J")),
            "tipo_hi": kind, "fecha_postura": posture, "edad_repro": number(r.get("D")),
            "fecha_ingreso": date_in, "cantidad_inicial": qty, "documento": doc,
            "responsable": txt(r.get("K")), "observacion": txt(r.get("L")), "origen": "EXCEL HISTÓRICO",
            "codigo_excel": txt(r.get("A")), "fila_excel": r["_fila"], "importacion_id": batch,
            "creado_en": stamp(),
        })
        parts.append(part)
        code_map[txt(r.get("A"))].append(pid)
        moves.append(fields("movimientos", {
            "id_movimiento": "MOV-" + uuid.uuid5(NS, digest + ":I:" + str(r["_fila"])).hex[:20].upper(),
            "id_operacion": "LEG-" + digest[:8].upper() + "-R" + str(r["_fila"]),
            "fecha_movimiento": date_in, "planta": "PUC", "almacen": "ALM-PUC", "id_partida": pid,
            "tipo": "INGRESO", "cantidad": qty, "variacion": qty, "documento": doc,
            "responsable": txt(r.get("K")), "importacion_id": batch, "creado_en": stamp(),
        }))
    type_map = {"carga": "CARGA", "transferencia": "TRANSFERENCIA_HISTORICA", "baja": "BAJA",
                "ajuste +": "AJUSTE +", "ajuste -": "AJUSTE -"}
    for m in mm:
        if not 10 <= m["_fila"] <= 1009 or not txt(m.get("B")):
            continue
        ids = code_map.get(txt(m.get("B")), [])
        kind = type_map.get(txt(m.get("C")).casefold())
        qty, moved = number(m.get("D")), epoch_excel(m.get("A"))
        if len(ids) != 1 or not kind or qty <= 0 or not parse_date(moved):
            issues.append(f"Movimientos, fila {m['_fila']}: referencia ambigua o datos no válidos")
            continue
        moves.append(fields("movimientos", {
            "id_movimiento": "MOV-" + uuid.uuid5(NS, digest + ":M:" + str(m["_fila"])).hex[:20].upper(),
            "id_operacion": "LEG-" + digest[:8].upper() + "-M" + str(m["_fila"]),
            "fecha_movimiento": moved, "planta": "PUC", "almacen": "ALM-PUC", "id_partida": ids[0],
            "tipo": kind, "cantidad": qty, "variacion": qty if kind == "AJUSTE +" else -qty,
            "id_maquina": "", "documento": txt(m.get("L")), "responsable": txt(m.get("M")),
            "causa": txt(m.get("R")), "observacion": txt(m.get("N")),
            "importacion_id": batch, "creado_en": stamp(),
        }))
    duplicates = {c: n for c, n in Counter(p["codigo_excel"] for p in parts).items() if c and n > 1}
    return {"partidas": parts, "movimientos": moves, "issues": issues, "duplicates": duplicates,
            "batch": batch, "incoming": sum(number(p["cantidad_inicial"]) for p in parts),
            "outgoing": sum(number(m["cantidad"]) for m in moves if m["tipo"] == "CARGA"),
            "balance": sum(number(m["variacion"]) for m in moves)}

def legacy_v31_plan(old_receipts, old_moves):
    """Convierte hojas HI_PUC_* a IT4_* sin crear stock nuevo en destino por traslados antiguos."""
    digest = hashlib.sha256(("|".join(x.get("id_recepcion", "") for x in old_receipts)
                             + "|".join(x.get("id_movimiento", "") for x in old_moves)).encode()).hexdigest()
    import_id = "V31-" + digest[:18].upper()
    entries, movements, issues, old_ids = [], [], [], {}
    for old in old_receipts:
        key = txt(old.get("id_recepcion"))
        qty = number(old.get("cantidad_hi"))
        f = txt(old.get("fecha_ingreso"))
        posture = txt(old.get("fecha_postura"))
        if not key or key in old_ids or qty <= 0 or not parse_date(f) or not parse_dt(posture):
            issues.append(f"Recepción {key or '(vacía)'}: ID duplicado o datos inválidos")
            continue
        if txt(old.get("tipo_hi")).upper() not in TIPOS_HI:
            issues.append(f"Recepción {key}: tipo HI no reconocido")
            continue
        pid = "PART-" + uuid.uuid5(NS, "V31:" + key).hex[:20].upper()
        old_ids[key] = pid
        part = fields("partidas", {"id_partida": pid, "planta": "PUC", "almacen": "ALM-PUC",
            "ubicacion": old.get("ubicacion", ""), "lote": source_id(old.get("lote")),
            "granja": "", "procedencia": old.get("origen", ""),
            "tipo_hi": txt(old.get("tipo_hi")).upper(), "fecha_postura": posture,
            "edad_repro": number(old.get("edad_repro")), "fecha_ingreso": f,
            "cantidad_inicial": qty, "documento": old.get("guia_recepcion", ""),
            "responsable": old.get("responsable", ""), "observacion": old.get("observacion", ""),
            "origen": "MIGRACIÓN V3.1", "codigo_excel": old.get("codigo_excel", ""),
            "fila_excel": old.get("fila_excel", ""), "importacion_id": import_id,
            "creado_en": old.get("creado_en") or stamp()})
        entries.append(part)
        movements.append(fields("movimientos", {
            "id_movimiento": "MOV-" + uuid.uuid5(NS, "V31:ING:" + key).hex[:20].upper(),
            "id_operacion": "MIG-" + key, "fecha_movimiento": f,
            "planta": "PUC", "almacen": "ALM-PUC", "id_partida": pid,
            "tipo": "INGRESO", "cantidad": qty, "variacion": qty,
            "documento": part["documento"], "responsable": part["responsable"],
            "importacion_id": import_id, "creado_en": stamp(),
        }))
    for old in old_moves:
        key = txt(old.get("id_recepcion"))
        pid = old_ids.get(key)
        kind = txt(old.get("tipo")).upper()
        if kind == "TRANSFERENCIA":
            kind = "TRANSFERENCIA_HISTORICA"
        qty, dt = number(old.get("cantidad_hi")), txt(old.get("fecha_movimiento"))
        if not pid or kind not in ("CARGA", "TRANSFERENCIA_HISTORICA", "BAJA", "AJUSTE +", "AJUSTE -") or qty <= 0 or not parse_date(dt):
            issues.append(f"Movimiento {old.get('id_movimiento', '')}: partida o campos inválidos")
            continue
        oid = txt(old.get("id_movimiento"))
        if not oid:
            issues.append("Movimiento sin ID original; no se importará automáticamente")
            continue
        movements.append(fields("movimientos", {
            "id_movimiento": "MOV-" + uuid.uuid5(NS, "V31:EV:" + oid).hex[:20].upper(),
            "id_operacion": "MIG-" + (txt(old.get("id_operacion")) or oid),
            "fecha_movimiento": dt[:10], "planta": "PUC", "almacen": "ALM-PUC",
            "id_partida": pid, "tipo": kind, "cantidad": qty,
            "variacion": qty if kind == "AJUSTE +" else -qty,
            "id_maquina": old.get("incubadora", ""), "documento": old.get("documento", ""),
            "responsable": old.get("responsable", ""), "causa": old.get("causa", ""),
            "observacion": old.get("observacion", ""),
            "importacion_id": import_id, "creado_en": old.get("creado_en") or stamp(),
        }))
    test_data = blank()
    test_data["partidas"], test_data["movimientos"] = entries, movements
    if any(x["saldo"] < 0 for x in inventory(test_data, now().date())):
        issues.append("Saldos negativos encontrados al conciliar versión 3.1")
    return {"partidas": entries, "movimientos": movements, "issues": issues,
            "incoming": sum(number(x["cantidad_inicial"]) for x in entries),
            "balance": sum(number(x["variacion"]) for x in movements),
            "importacion_id": import_id}


def read_legacy_v31():
    """Lee las dos hojas antiguas en una única solicitud de lectura."""
    book = workbook()
    existing = {s.title for s in book.worksheets()}
    names = ("HI_PUC_Recepciones", "HI_PUC_Movimientos")
    if not all(n in existing for n in names):
        return None
    result = []
    for values in batch_values(names, book=book):
        if not values:
            result.append([])
            continue
        heads = values[0]
        result.append([dict(zip(heads,row + [""]*(len(heads)-len(row)))) for row in values[1:]
                       if any(txt(v) for v in row)])
    return legacy_v31_plan(*result)


# --------- Google Sheets: 10 hojas IT4_ separadas de datos anteriores ---------
@st.cache_resource(show_spinner=False)
def workbook():
    try:
        cfg = dict(st.secrets["gcp_service_account"])
        book_id = txt(st.secrets.get("SPREADSHEET_ID") or SHEET_ID_DEFAULT)
        cred = Credentials.from_service_account_info(cfg, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        return gspread.authorize(cred).open_by_key(book_id)
    except KeyError as exc:
        raise RuntimeError("Falta [gcp_service_account] en Secrets de Streamlit.") from exc
    except Exception as exc:
        raise RuntimeError(f"No se pudo abrir Google Sheets: {exc}") from exc


def batch_values(names, *, book=None, first_two=False):
    """Consulta muchas pestañas en UNA lectura (Sheets values.batchGet).

    El orden de valueRanges coincide con el de ranges, incluso si una hoja está vacía.
    """
    book = book if book is not None else workbook()
    ranges = [f"'{name}'!A1:Z2" if first_two else f"'{name}'" for name in names]
    response = book.values_batch_get(ranges, params={"valueRenderOption": "FORMATTED_VALUE"})
    value_ranges = response.get("valueRanges", [])
    if len(value_ranges) != len(names):
        raise RuntimeError("Google Sheets devolvió una respuesta incompleta. No se usarán datos parciales.")
    return [entry.get("values", []) for entry in value_ranges]


@st.cache_resource(show_spinner=False)
def setup():
    """Inicializa tablas y verifica las 10 cabeceras con una sola lectura.

    Se conserva el mapa de hojas en memoria para que las escrituras no vuelvan a
    consultar metadatos en cada operación.
    """
    book = workbook()
    sheets = {s.title: s for s in book.worksheets()}
    for name, headers in TABLAS.values():
        if name not in sheets:
            w = book.add_worksheet(title=name, rows=3000, cols=len(headers))
            w.append_row(headers, value_input_option="RAW")
            sheets[name] = w
    names = [name for name, _ in TABLAS.values()]
    preview = dict(zip(names, batch_values(names, book=book, first_two=True)))
    for name, headers in TABLAS.values():
        if not preview[name] or preview[name][0] != headers:
            raise RuntimeError(f"Los encabezados de '{name}' no coinciden con esta versión. No se modificarán.")
    initial_rows = {}
    if len(preview[TABLAS["plantas"][0]]) == 1:
        initial_rows["plantas"] = [{"id_planta": code, "nombre": nombre, "activo": "SI"}
                                   for code, nombre in PLANTAS.items()]
    if len(preview[TABLAS["almacenes"][0]]) == 1:
        initial_rows["almacenes"] = [{"id_almacen": f"ALM-{code}", "id_planta": code,
                                       "nombre": "Almacén principal (provisional)",
                                       "activo": "SI", "creado_en": stamp()} for code in PLANTAS]
    if initial_rows:
        batch_write(initial_rows, book=book, sheet_map=sheets)
    return sheets


def cell_value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"numberValue": v}
    if isinstance(v, float):
        return {"numberValue": v}
    # stringValue: evita que IDs/documentos que comienzan con '=' se ejecuten como fórmulas
    return {"stringValue": txt(v)}


def batch_write(groups, book=None, sheet_map=None):
    """Un API batchUpdate: agregar filas en varias hojas en una sola solicitud."""
    book = book if book is not None else workbook()
    # setup() está en caché y conserva los IDs. No pedir worksheets() al escribir.
    sheet_map = sheet_map if sheet_map is not None else setup()
    requests = []
    for kind, rows in groups.items():
        if not rows:
            continue
        name, headers = TABLAS[kind]
        values = [{"values": [{"userEnteredValue": cell_value(row.get(c, ""))} for c in headers]}
                  for row in rows]
        # Una solicitud por bloque; permite operaciones de varias pestañas conjuntamente.
        requests.append({"appendCells": {"sheetId": sheet_map[name].id, "rows": values,
                                          "fields": "userEnteredValue"}})
    if requests:
        book.batch_update({"requests": requests})
        read_sheets.clear()


@st.cache_data(ttl=60, show_spinner=False)
def read_sheets():
    """Un solo batchGet para todas las tablas, con caché compartida 60 segundos.

    Las escrituras invalidan esta caché y los formularios críticos fuerzan una
    relectura antes de comprobar stock.
    """
    result = blank()
    names = [name for name, _ in TABLAS.values()]
    groups = batch_values(names)
    for (kind, (_, cols)), values in zip(TABLAS.items(), groups):
        if not values:
            continue
        if values[0] != cols:
            raise RuntimeError(f"Encabezados inesperados en {TABLAS[kind][0]}; lectura cancelada.")
        result[kind] = [dict(zip(cols, (row + [""] * len(cols))[:len(cols)]))
                        for row in values[1:] if any(txt(v) for v in row)]
    return result


def read_fresh():
    read_sheets.clear()
    return read_sheets()


def require_unique(data, key, field, value):
    if any(txt(r.get(field)) == txt(value) for r in data[key]):
        raise ValueError(f"Operación {value} ya registrada. Actualiza la pantalla.")


def pending_id(k, prefix="OP"):
    key = "token_" + k
    if key not in st.session_state:
        st.session_state[key] = uid(prefix)
    return st.session_state[key]


def reset_id(k):
    st.session_state.pop("token_" + k, None)
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
    read_sheets.clear()


def result(msg):
    st.session_state["notice"] = msg
    st.rerun()


# ------------------ Kardex e inventarios, independientes de la UI ------------------
def inventory(data, cutoff=None):
    cutoff = cutoff or now().date()
    variance = defaultdict(int)
    for m in data["movimientos"]:
        d = parse_date(m.get("fecha_movimiento"))
        if d and d <= cutoff:
            variance[txt(m.get("id_partida"))] += number(m.get("variacion"))
    out = []
    for r in data["partidas"]:
        d = parse_date(r.get("fecha_ingreso"))
        if d is None or d > cutoff:
            continue
        a = dict(r)
        a["saldo"] = variance.get(txt(r.get("id_partida")), 0)
        a["cantidad_inicial"] = number(r.get("cantidad_inicial"))
        a["edad_repro"] = number(r.get("edad_repro"))
        f = parse_dt(r.get("fecha_postura"))
        a["dias_postura"] = round((datetime.combine(cutoff, dt_time()) - f).total_seconds() / 86400, 2) if f else None
        out.append(a)
    return out


def limits(data, plant):
    defaults = {"OBJ_MENOR_50": 7, "OBJ_50_59": 5, "OBJ_60_MAS": 3}
    for p in data["parametros"]:
        if p.get("planta") == plant and p.get("clave") in defaults:
            n = number(p.get("valor"), -1)
            if 0 < n <= 30:
                defaults[p["clave"]] = n
    return defaults


def status(r, data):
    if r["saldo"] <= 0:
        return "Sin saldo" if r["saldo"] == 0 else "Saldo negativo"
    if not r["edad_repro"] or r["dias_postura"] is None:
        return "Sin datos"
    p = limits(data, r["planta"])
    limit = p["OBJ_MENOR_50"] if r["edad_repro"] < 50 else p["OBJ_50_59"] if r["edad_repro"] < 60 else p["OBJ_60_MAS"]
    delta = limit - r["dias_postura"]
    return "Objetivo superado" if delta < 0 else "Prioridad hoy" if delta <= 1 else "En plazo"


def asof_options(data, plant, wh, cutoff, kind=None):
    items = [r for r in inventory(data, cutoff) if r["planta"] == plant and r["almacen"] == wh and r["saldo"] > 0]
    if kind and kind != "Todos":
        items = [r for r in items if r["tipo_hi"] == kind]
    return sorted(items, key=lambda r: (r["fecha_postura"], r["lote"]))


def validate_deltas(data, new_rows):
    """Valida stock al corte y posterior; también rechaza cronología negativa."""
    current = {r["id_partida"]: r for r in data["partidas"]}
    moves = defaultdict(list)
    for m in data["movimientos"] + new_rows:
        moves[txt(m.get("id_partida"))].append(m)
    for rid in {txt(r["id_partida"]) for r in new_rows}:
        part = current.get(rid)
        if part is None:
            raise ValueError("Partida inexistente o no confirmada.")
        base = parse_date(part.get("fecha_ingreso"))
        by_day = defaultdict(int)
        for m in moves[rid]:
            day = parse_date(m.get("fecha_movimiento"))
            if not day or not base or day < base:
                raise ValueError("Un movimiento no puede preceder a la recepción de la partida.")
            by_day[day] += number(m.get("variacion"))
        running = 0
        for day in sorted(by_day):
            running += by_day[day]
            if running < 0:
                raise ValueError(f"El saldo de la partida {rid[-8:]} sería negativo al {day}.")


def chosen_lines(data, plant, wh, code):
    opts = asof_options(data, plant, wh, now().date())
    if not opts:
        st.info("No hay partidas con existencias disponibles en este almacén.")
        return []
    table = pd.DataFrame([{"Partida ID": r["id_partida"], "Lote": r["lote"], "Clase": r["tipo_hi"],
                           "Postura": r["fecha_postura"][:16], "Ubicación": r["ubicacion"],
                           "Disponible": r["saldo"], "A utilizar": 0} for r in opts])
    edited = st.data_editor(table, hide_index=True, use_container_width=True,
        key=f"editor_{code}_{st.session_state.get('editor_version',0)}", height=min(500, 90 + len(opts) * 34),
        disabled=["Partida ID", "Lote", "Clase", "Postura", "Ubicación", "Disponible"],
        column_config={"Partida ID": st.column_config.TextColumn(width="small"),
                       "A utilizar": st.column_config.NumberColumn(min_value=0, step=1),
                       "Disponible": st.column_config.NumberColumn(format="%d")})
    return [{"id_partida": txt(row["Partida ID"]), "cantidad": number(row["A utilizar"]),
             "disponible": number(row["Disponible"])}
            for _, row in edited.iterrows() if number(row["A utilizar"]) > 0]


def validate_lines(lines):
    if not lines:
        raise ValueError("Selecciona al menos una cantidad mayor a cero.")
    if any(x["cantidad"] <= 0 or x["cantidad"] > x["disponible"] for x in lines):
        raise ValueError("Hay cantidades que exceden el saldo disponible.")
    if len({x["id_partida"] for x in lines}) != len(lines):
        raise ValueError("No se permite repetir una partida en la misma operación.")


def make_mov(op, part, kind, qty, d, doc, operator, machine="", transfer="", cause="", obs="", mid=""):
    return fields("movimientos", {"id_movimiento": mid or uid("MOV"), "id_operacion": op,
       "fecha_movimiento": d.isoformat() if isinstance(d, date) else d,
       "planta": part["planta"], "almacen": part["almacen"], "id_partida": part["id_partida"],
       "tipo": kind, "cantidad": qty, "variacion": qty if kind in ("INGRESO", "AJUSTE +") else -qty,
       "id_maquina": machine, "id_transferencia": transfer, "documento": doc, "responsable": operator,
       "causa": cause, "observacion": obs, "creado_en": stamp()})


def commit_consumption(kind, code, lines, plant, wh, date_op, document, operator, machine="", dest="", cause="", obs=""):
    validate_lines(lines)
    if not txt(document) or not txt(operator):
        raise ValueError("El documento y el responsable son obligatorios.")
    if date_op > now().date():
        raise ValueError("No es posible registrar operaciones con fecha futura.")
    data = read_fresh()
    operation = pending_id(code)
    require_unique(data, "movimientos", "id_operacion", operation)
    lookup = {r["id_partida"]: r for r in data["partidas"]}
    rows = []
    for item in lines:
        p = lookup.get(item["id_partida"])
        if not p or p["planta"] != plant or p["almacen"] != wh:
            raise ValueError("Una partida ya no pertenece a este almacén.")
        rows.append(make_mov(operation, p, kind, item["cantidad"], date_op, document, operator,
                             machine=machine, cause=cause, obs=obs))
    validate_deltas(data, rows)
    batch_write({"movimientos": rows})
    reset_id(code)
    result(f"{kind}: {fmt(sum(x['cantidad'] for x in lines))} HI registrados en {PLANTAS[plant]}.")


# -------------------- Estilos, navegación y componentes --------------------
st.set_page_config(page_title="IncubaTrack Regional | Don Pollo", page_icon="🥚", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {background: #f6f8fb;}
.block-container {max-width: 1580px; padding-top: 1.1rem; padding-bottom: 4rem;}
[data-testid="stSidebar"] {background:#fff; border-right:1px solid #e4eaf1;}
[data-testid="stSidebar"] .stRadio [data-testid="stWidgetLabel"] {display:none;}
[data-testid="stMetric"] {background:#fff; border:1px solid #e4eaf1; border-top:4px solid #147cba; border-radius:12px; padding:14px 17px; box-shadow:0 5px 22px rgba(22,52,82,.035);}
[data-testid="stMetricLabel"] {color:#5c7087; font-weight:650;}
[data-testid="stMetricValue"] {color:#173c58; letter-spacing:-.035em;}
.stButton button,.stFormSubmitButton button {border-radius:9px; min-height:2.55rem; font-weight:650;}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"] {background:#ea7120; border:1px solid #ea7120; color:white;}
.stButton button[kind="primary"]:hover,.stFormSubmitButton button[kind="primary"]:hover {background:#d66114; border-color:#d66114;}
div[data-testid="stVerticalBlockBorderWrapper"]>div {border-color:#e2e9f1; border-radius:12px;}
.hero {background:#fff;border:1px solid #e4eaf1;border-radius:13px;padding:20px 23px 18px;margin:0 0 18px;}
.hero h1 {margin:0;font-size:1.48rem;color:#173c58;line-height:1.25;font-weight:750;}
.hero p {margin:.4rem 0 0;color:#6d7e8e;font-size:.91rem;}
.linecaption {font-size:.76rem;color:#6b7e8f;}
[data-testid="stDataFrame"] {border:1px solid #e3eaf1;border-radius:10px;}
</style>""", unsafe_allow_html=True)


def header(title, subtitle):
    st.markdown(f'<div class="hero"><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>', unsafe_allow_html=True)


def frame(rows, height=430):
    d = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if d.empty:
        st.info("Sin registros para los filtros seleccionados.")
    else:
        st.dataframe(d, use_container_width=True, hide_index=True, height=height)


def csv_download(label, rows, filename):
    if isinstance(rows, pd.DataFrame):
        d = rows
    else:
        d = pd.DataFrame(rows)
    st.download_button(label, d.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name=filename, mime="text/csv", use_container_width=True)


def plant_warehouses(data, plant):
    return [x for x in data["almacenes"] if x["id_planta"] == plant and x.get("activo") == "SI"]


def active_machines(data, plant):
    return [x for x in data["maquinas"] if x["id_planta"] == plant and x.get("activo") == "SI"]


def operation_scope(data, side_plant, key):
    plant = side_plant if side_plant != "REG" else st.selectbox("Planta operativa", list(PLANTAS),
                 format_func=lambda x: PLANTAS[x], key=f"pl_{key}")
    warehouses = plant_warehouses(data, plant)
    if not warehouses:
        st.error("No hay almacenes activos para esta planta. Configúralos en Catálogos.")
        st.stop()
    ware = st.selectbox("Almacén", [w["id_almacen"] for w in warehouses],
         format_func=lambda i: next(w["nombre"] for w in warehouses if w["id_almacen"] == i), key=f"wh_{key}")
    return plant, ware


def filtered_inventory(data, cutoff, side_plant):
    values = inventory(data, cutoff)
    return [r for r in values if side_plant == "REG" or r["planta"] == side_plant]


def stock_view_rows(data, cutoff, scope):
    out = []
    for r in filtered_inventory(data, cutoff, scope):
        out.append({"Planta": PLANTAS.get(r["planta"], r["planta"]), "Almacén": r["almacen"],
           "Ubicación": r["ubicacion"], "Lote": r["lote"], "Clase": r["tipo_hi"],
           "Postura": r["fecha_postura"][:16], "Edad repro": r["edad_repro"],
           "Recepción": r["fecha_ingreso"], "HI ingresados": r["cantidad_inicial"],
           "Saldo HI": r["saldo"], "Cajas completas": max(r["saldo"], 0)//HI_CAJA,
           "Días postura": r["dias_postura"], "Estado": status(r, data), "Documento": r["documento"],
           "Partida ID": r["id_partida"]})
    return pd.DataFrame(out)


def show_dashboard(data, scope):
    header("Centro de control regional", "Existencias y actividad de Tarapoto, Pucacaca y Loreto en una única vista.")
    cutoff = st.date_input("Fecha de corte", value=now().date(), max_value=now().date(), key="dash_cutoff")
    inv = filtered_inventory(data, cutoff, scope)
    ids = {r["id_partida"] for r in inv}
    moves = [m for m in data["movimientos"] if m["id_partida"] in ids and
             parse_date(m.get("fecha_movimiento")) and parse_date(m["fecha_movimiento"]) <= cutoff]
    incoming = sum(number(m["cantidad"]) for m in moves if m["tipo"] == "INGRESO")
    load = sum(number(m["cantidad"]) for m in moves if m["tipo"] == "CARGA")
    tr_out = sum(number(m["cantidad"]) for m in moves if m["tipo"] == "TRANSFERENCIA_SALIDA")
    available = sum(r["saldo"] for r in inv)
    pending = pending_transfer_lines(data, cutoff, scope)
    a,b,c,d,e = st.columns(5)
    a.metric("Saldo disponible", fmt(available))
    b.metric("Ingresos HI", fmt(incoming))
    c.metric("Cargados a máquinas", fmt(load))
    d.metric("Enviados a otras plantas", fmt(tr_out))
    e.metric("En tránsito al destino", fmt(sum(x["pendiente"] for x in pending)))
    st.caption("Los indicadores de movimientos son acumulados hasta el corte. El tránsito no forma parte del saldo disponible de ninguna planta.")
    lft, rgt = st.columns([1.1, .9], gap="large")
    with lft:
        st.subheader("Disponibilidad por planta")
        by = pd.DataFrame([{"Planta": PLANTAS[p], "Saldo HI": sum(r["saldo"] for r in inv if r["planta"] == p)} for p in PLANTAS])
        st.bar_chart(by.set_index("Planta"), height=300)
    with rgt:
        st.subheader("Distribución por clase")
        by = pd.DataFrame([{"Clase": c, "HI": sum(r["saldo"] for r in inv if r["tipo_hi"] == c)} for c in TIPOS_HI])
        st.bar_chart(by.set_index("Clase"), height=300)
    st.subheader("Alertas operativas")
    alerts = [r for r in inv if r["saldo"] > 0 and status(r,data) in ("Objetivo superado", "Prioridad hoy")]
    a,b,c = st.columns(3)
    a.metric("HI por priorizar", fmt(sum(r["saldo"] for r in alerts)))
    b.metric("Partidas activas", fmt(sum(r["saldo"] > 0 for r in inv)))
    c.metric("Partidas con saldo negativo", fmt(sum(r["saldo"] < 0 for r in inv)))
    if pending:
        st.warning(f"Existen {len(pending)} líneas de transferencia con recepción pendiente. Revisa Traslados.")
    if any(r["saldo"] < 0 for r in inv):
        st.error("Se encontraron saldos negativos históricos. Revisar Auditoría antes de operar.")
    frame([{"Planta": PLANTAS[r["planta"]], "Lote": r["lote"], "Clase": r["tipo_hi"],
        "Postura": r["fecha_postura"][:16], "Saldo HI": r["saldo"], "Estado": status(r,data)} for r in alerts[:35]], 280)
    st.caption("Alertas de antigüedad: se aplican parámetros de ejemplo 7/5/3 días por edad de reproductora, hasta que Incubación los valide.")


def show_inventory(data, scope):
    header("Existencias por almacén", "Saldos calculados desde el kardex; cada recepción mantiene su identidad y fecha/hora de postura.")
    cutoff = st.date_input("Fecha de corte", value=now().date(), max_value=now().date(), key="inv_cutoff")
    tab = stock_view_rows(data, cutoff, scope)
    if tab.empty:
        st.info("Aún no hay existencias para el corte seleccionado.")
        return
    a,b,c = st.columns(3)
    plant_opts = sorted(tab["Planta"].unique().tolist())
    plants = a.multiselect("Plantas", plant_opts, default=plant_opts)
    classes = b.multiselect("Clases", list(TIPOS_HI), default=list(TIPOS_HI))
    search = c.text_input("Buscar lote, guía o ID", placeholder="Ej. 237, SF RP01, guía...")
    show = tab[tab["Planta"].isin(plants) & tab["Clase"].isin(classes)].copy()
    if search:
        mask = show[["Lote", "Documento", "Partida ID"]].fillna("").astype(str).apply(
           lambda col: col.str.contains(re.escape(search), case=False), axis=0).any(axis=1)
        show = show[mask]
    v1,v2,v3 = st.columns(3)
    v1.metric("Saldo filtrado", fmt(show["Saldo HI"].sum()))
    v2.metric("Cajas completas", fmt(max(0,show["Saldo HI"].sum())//HI_CAJA))
    v3.metric("Recepciones con saldo", fmt((show["Saldo HI"]>0).sum()))
    frame(show.sort_values(["Postura", "Planta"], ascending=[True,True]), 540)
    csv_download("Exportar existencias (CSV)", show, "incubatrack_existencias.csv")
    st.caption("Leyenda: Objetivo superado = sobrepasó los días configurados; Prioridad hoy = ≤1 día restante; En plazo = dentro del objetivo.")


def show_receipts(data, scope):
    header("Registrar recepción de HI", "Ingreso documentado por planta y almacén; los saldos se generan desde el movimiento de entrada.")
    plant, wh = operation_scope(data, scope, "rec")
    with st.form("form_receipt", clear_on_submit=True):
        c1,c2,c3 = st.columns(3)
        lote = c1.text_input("Lote de reproductoras *")
        clase = c2.selectbox("Clase HI", TIPOS_HI)
        qty = c3.number_input("Cantidad HI *", min_value=1, step=1)
        c4,c5,c6 = st.columns(3)
        fecha = c4.date_input("Fecha de recepción *", value=now().date(), max_value=now().date())
        fp = c5.date_input("Fecha de postura *", value=now().date(), max_value=now().date())
        hp = c6.time_input("Hora de postura (si se conoce)", value=dt_time(0,0), step=1800)
        c7,c8,c9 = st.columns(3)
        edad = c7.number_input("Edad reproductoras (semanas)", 0, 100, value=0)
        granja = c8.text_input("Granja / proveedor")
        ubicacion = c9.text_input("Ubicación / cámara", placeholder="Ej. Estante 2")
        c10,c11 = st.columns(2)
        doc = c10.text_input("Guía / documento *")
        operator = c11.text_input("Responsable *", value=st.session_state.get("operador", ""))
        note = st.text_area("Observaciones sanitarias y de recepción", height=75)
        confirm = st.checkbox("Confirmo que los datos y la cantidad corresponden a una recepción real")
        submitted = st.form_submit_button("Registrar recepción", type="primary")
    if submitted:
        try:
            if not all([lote.strip(), doc.strip(), operator.strip(), confirm]):
                raise ValueError("Completa lote, documento, responsable y confirmación.")
            if fp > fecha:
                raise ValueError("La postura no puede ser posterior a la recepción.")
            token = pending_id("rec", "PART")
            fresh = read_fresh()
            require_unique(fresh, "partidas", "id_partida", token)
            # Impide un doble ingreso accidental del mismo comprobante y partida.
            equal = [p for p in fresh["partidas"] if p.get("planta") == plant
                  and p.get("almacen") == wh and source_id(p.get("lote")) == source_id(lote)
                  and p.get("tipo_hi") == clase and parse_date(p.get("fecha_ingreso")) == fecha
                  and txt(p.get("fecha_postura")) == datetime.combine(fp, hp).isoformat(timespec="seconds")
                  and txt(p.get("documento")).casefold() == doc.strip().casefold()
                  and number(p.get("cantidad_inicial")) == int(qty)]
            if equal:
                raise ValueError("Ya existe una recepción idéntica (lote, clase, postura, cantidad, fecha y guía). "
                                 "Verifica el registro antes de duplicarlo.")
            part = fields("partidas", {"id_partida": token, "planta": plant, "almacen": wh,
               "ubicacion": ubicacion, "lote": source_id(lote), "granja": granja,
               "procedencia": granja, "tipo_hi": clase, "fecha_postura": datetime.combine(fp,hp).isoformat(timespec="seconds"),
               "edad_repro": edad, "fecha_ingreso": fecha.isoformat(), "cantidad_inicial": int(qty),
               "documento": doc, "responsable": operator, "observacion": note, "origen": "EXTERNO", "creado_en": stamp()})
            mov = make_mov(token, part, "INGRESO", int(qty), fecha, doc, operator, obs=note)
            batch_write({"partidas": [part], "movimientos": [mov]})
            reset_id("rec")
            result(f"Recepción creada: {fmt(qty)} HI del lote {lote} en {PLANTAS[plant]}.")
        except Exception as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("Recepciones recientes")
    rec = [r for r in data["partidas"] if scope == "REG" or r["planta"] == scope]
    frame([{"Fecha": r["fecha_ingreso"], "Planta": PLANTAS.get(r["planta"],r["planta"]),
       "Lote": r["lote"], "Clase": r["tipo_hi"], "Cantidad HI":number(r["cantidad_inicial"]),
       "Guía": r["documento"], "Responsable": r["responsable"]} for r in rec[-50:][::-1]], 310)


def show_loads(data, scope):
    header("Cargas por incubadora", "Una carga puede utilizar varias recepciones, y cada línea conserva el vínculo con su lote de origen.")
    plant, wh = operation_scope(data, scope, "load")
    mach = active_machines(data, plant)
    if not mach:
        st.warning("Antes de registrar una carga, configura las incubadoras reales de esta planta en Catálogos.")
        return
    a,b,c = st.columns(3)
    mid = a.selectbox("Máquina de incubación *", [m["id_maquina"] for m in mach],
        format_func=lambda id_: next(m["nombre"] for m in mach if m["id_maquina"] == id_))
    fecha = b.date_input("Fecha de carga", value=now().date(), max_value=now().date(), key="load_date")
    doc = c.text_input("Orden / documento de carga *", key="load_doc")
    st.markdown("**Selecciona los huevos que ingresarán a la máquina:**")
    lines = chosen_lines(data, plant, wh, "load")
    count = sum(x["cantidad"] for x in lines)
    a,b = st.columns([3,1])
    operator = a.text_input("Responsable *", value=st.session_state.get("operador", ""), key="load_resp")
    b.metric("Total a cargar", fmt(count))
    notes = st.text_area("Observaciones de carga", key="load_notes")
    confirm = st.checkbox("Confirmo la máquina, la orden y las cantidades seleccionadas", key="load_ok")
    if st.button("Confirmar carga de HI", type="primary", disabled=count<=0, use_container_width=True):
        try:
            if not confirm:
                raise ValueError("Confirma que verificaste la carga.")
            recent = read_fresh()
            if not any(m["id_maquina"] == mid and m["id_planta"] == plant for m in active_machines(recent, plant)):
                raise ValueError("La máquina no pertenece a esta planta.")
            commit_consumption("CARGA", "load", lines, plant, wh, fecha, doc, operator, machine=mid, obs=notes)
        except Exception as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("Últimas cargas")
    ms = [m for m in data["movimientos"] if m["tipo"] == "CARGA" and (scope == "REG" or m["planta"] == scope)]
    frame([{"Fecha":m["fecha_movimiento"], "Planta": PLANTAS.get(m["planta"],m["planta"]),
      "Máquina":m["id_maquina"] or "Pendiente (histórico)","Partida":m["id_partida"],
      "HI":number(m["cantidad"]),"Orden":m["documento"],"Responsable":m["responsable"]} for m in ms[-80:][::-1]], 300)


def pending_transfer_lines(data, cutoff=None, scope="REG"):
    cutoff = cutoff or now().date()
    heads = {t["id_transferencia"]:t for t in data["transferencias"] if parse_date(t["fecha_despacho"]) and parse_date(t["fecha_despacho"]) <= cutoff}
    received = defaultdict(int)
    for r in data["confirmaciones"]:
        dt = parse_date(r.get("fecha_recepcion"))
        if dt and dt <= cutoff:
            received[r["id_linea"]] += number(r["cantidad_conforme"])+number(r["cantidad_rechazada"])+number(r["cantidad_faltante"])
    rows = []
    for line in data["lineas"]:
        h = heads.get(line["id_transferencia"])
        if h is None or scope not in ("REG", h["planta_origen"], h["planta_destino"]):
            continue
        sent = number(line["cantidad_enviada"])
        pend = sent - received[line["id_linea"]]
        if pend > 0:
            rows.append({**line, **h, "pendiente":pend, "recibido_total":received[line["id_linea"]]})
    return rows


def show_transfers(data, scope):
    header("Transferencias entre plantas", "Despacho → tránsito → confirmación en destino. Solo los huevos conformes ingresan al inventario receptor.")
    tab1,tab2,tab3 = st.tabs(["Despachar", "Confirmar llegada", "Seguimiento"])
    with tab1:
        plant, wh = operation_scope(data, scope, "send")
        destinations = [p for p in PLANTAS if p != plant]
        c1,c2 = st.columns(2)
        dest = c1.selectbox("Planta destino *", destinations, format_func=lambda c:PLANTAS[c], key="dest_plant")
        dest_whs = plant_warehouses(data,dest)
        if not dest_whs:
            st.error("La planta destino debe tener un almacén activo.")
        else:
            dest_wh = c2.selectbox("Almacén destino *", [x["id_almacen"] for x in dest_whs],
                         format_func=lambda i:next(w["nombre"] for w in dest_whs if w["id_almacen"]==i))
            a,b = st.columns(2)
            fecha = a.date_input("Fecha despacho",now().date(), max_value=now().date(), key="send_date")
            doc = b.text_input("Guía de remisión / documento *", key="send_doc")
            a,b,c = st.columns(3)
            carrier = a.text_input("Transportista", key="send_carrier")
            plate = b.text_input("Placa", key="send_plate")
            logtag = c.text_input("ID LogTag", key="send_logtag")
            st.markdown("**Detalle de huevos a transferir:**")
            lines = chosen_lines(data, plant, wh, "send")
            total = sum(x["cantidad"] for x in lines)
            a,b = st.columns([3,1])
            operator = a.text_input("Responsable de despacho *", value=st.session_state.get("operador", ""), key="send_resp")
            b.metric("HI a enviar",fmt(total))
            note = st.text_area("Observaciones del transporte",key="send_note")
            confirm = st.checkbox("Confirmo el destino, guía y cantidades despachadas",key="send_ok")
            if st.button("Registrar salida a tránsito",type="primary", disabled=total<=0, use_container_width=True):
                try:
                    if not (doc.strip() and operator.strip() and confirm):
                        raise ValueError("Documento, responsable y confirmación son obligatorios.")
                    validate_lines(lines)
                    fresh = read_fresh()
                    txid = pending_id("send","TR")
                    require_unique(fresh,"transferencias","id_transferencia",txid)
                    lookup = {p["id_partida"]:p for p in fresh["partidas"]}
                    moves, detail = [], []
                    for x in lines:
                        p = lookup.get(x["id_partida"])
                        if not p or p["planta"] != plant or p["almacen"] != wh:
                            raise ValueError("Hay partidas de otro almacén.")
                        moves.append(make_mov(txid,p,"TRANSFERENCIA_SALIDA",x["cantidad"],fecha,doc,operator,transfer=txid,obs=note))
                        detail.append(fields("lineas",{"id_linea":uid("LIN"),"id_transferencia":txid,
                             "id_partida_origen":p["id_partida"],"cantidad_enviada":x["cantidad"],"creado_en":stamp()}))
                    validate_deltas(fresh,moves)
                    head = fields("transferencias",{"id_transferencia":txid,"fecha_despacho":fecha.isoformat(),
                       "planta_origen":plant,"almacen_origen":wh,"planta_destino":dest,"almacen_destino":dest_wh,
                       "documento":doc,"responsable":operator,"transportista":carrier,"placa":plate,
                       "logtag":logtag,"observacion":note,"creado_en":stamp()})
                    batch_write({"transferencias":[head],"lineas":detail,"movimientos":moves})
                    reset_id("send")
                    result(f"Transferencia {txid}: {fmt(total)} HI despachados hacia {PLANTAS[dest]}.")
                except Exception as exc:
                    st.error(str(exc))
    with tab2:
        pending = pending_transfer_lines(data,scope=scope)
        if not pending:
            st.success("No existen transferencias pendientes en el ámbito seleccionado.")
        else:
            txs = sorted({x["id_transferencia"] for x in pending})
            descriptions = {x["id_transferencia"]: f"{x['id_transferencia']} · {PLANTAS[x['planta_origen']]} → {PLANTAS[x['planta_destino']]}" for x in pending}
            transfer_id = st.selectbox("Transferencia en tránsito",txs,format_func=lambda x:descriptions[x],key="arrival_tx")
            lines = [x for x in pending if x["id_transferencia"]==transfer_id]
            choice = st.selectbox("Partida enviada",[x["id_linea"] for x in lines],
                format_func=lambda id_:f"{id_[-8:]} · pendiente {fmt(next(l['pendiente'] for l in lines if l['id_linea']==id_))} HI")
            line = next(x for x in lines if x["id_linea"]==choice)
            p0 = next((p for p in data["partidas"] if p["id_partida"]==line["id_partida_origen"]),None)
            if p0 is None:
                st.error("La partida de origen no existe; requiere revisión de auditoría.")
            else:
                st.info(f"Origen: {PLANTAS[line['planta_origen']]} · Destino: {PLANTAS[line['planta_destino']]} · "
                        f"Lote: {p0['lote']} / {p0['tipo_hi']} · Pendiente: {fmt(line['pendiente'])} HI")
                with st.form("arrival_form"):
                    a,b,c = st.columns(3)
                    ok = a.number_input("HI conformes",min_value=0, max_value=int(line["pendiente"]),step=1)
                    reject = b.number_input("HI rechazados",min_value=0,max_value=int(line["pendiente"]),step=1)
                    missing = c.number_input("HI faltantes",min_value=0,max_value=int(line["pendiente"]),step=1)
                    a,b = st.columns(2)
                    f_arrive = a.date_input("Fecha recepción",now().date(),min_value=parse_date(line["fecha_despacho"]),max_value=now().date())
                    doc = b.text_input("Acta / guía de recepción *")
                    operator = st.text_input("Responsable receptor *",value=st.session_state.get("operador",""))
                    location = st.text_input("Ubicación física en destino",value=p0.get("ubicacion", ""))
                    note = st.text_area("Diferencias, embalaje y temperatura observada",height=75)
                    sure = st.checkbox("Confirmo la cantidad realmente recibida y las diferencias documentadas")
                    sent = st.form_submit_button("Confirmar recepción",type="primary")
                if sent:
                    try:
                        qty = int(ok)+int(reject)+int(missing)
                        if qty<=0 or qty>line["pendiente"]:
                            raise ValueError("Las cantidades deben sumar entre 1 y el pendiente de la línea.")
                        if not (doc.strip() and operator.strip() and sure):
                            raise ValueError("Documento, responsable y confirmación obligatorios.")
                        fresh = read_fresh()
                        latest = next((x for x in pending_transfer_lines(fresh,scope="REG") if x["id_linea"]==choice),None)
                        if latest is None or qty>latest["pendiente"]:
                            raise ValueError("El pendiente cambió desde que abriste el formulario. Actualiza la pantalla.")
                        confirmation_id = pending_id("arrival","CONF")
                        require_unique(fresh,"confirmaciones","id_confirmacion",confirmation_id)
                        parent = next(p for p in fresh["partidas"] if p["id_partida"]==latest["id_partida_origen"])
                        child_id = "PART-"+uuid.uuid5(NS,confirmation_id).hex[:20].upper() if ok>0 else ""
                        record = fields("confirmaciones",{"id_confirmacion":confirmation_id,"id_transferencia":transfer_id,
                            "id_linea":choice,"fecha_recepcion":f_arrive.isoformat(),"cantidad_conforme":int(ok),
                            "cantidad_rechazada":int(reject),"cantidad_faltante":int(missing),"id_partida_destino":child_id,
                            "documento":doc,"responsable":operator,"observacion":note,"creado_en":stamp()})
                        groups = {"confirmaciones":[record]}
                        if ok>0:
                            part = fields("partidas",{"id_partida":child_id,"planta":latest["planta_destino"],
                              "almacen":latest["almacen_destino"],"ubicacion":location,"lote":parent["lote"],
                              "granja":parent["granja"],"procedencia":parent["procedencia"],"tipo_hi":parent["tipo_hi"],
                              "fecha_postura":parent["fecha_postura"],"edad_repro":parent["edad_repro"],
                              "fecha_ingreso":f_arrive.isoformat(),"cantidad_inicial":int(ok),"documento":doc,
                              "responsable":operator,"observacion":note,"origen":"TRANSFERENCIA",
                              "id_partida_padre":parent["id_partida"],"id_transferencia":transfer_id,
                              "id_linea_transferencia":choice,"creado_en":stamp()})
                            movement = make_mov(confirmation_id,part,"INGRESO",int(ok),f_arrive,doc,operator,
                                               transfer=transfer_id,obs=note)
                            groups.update({"partidas":[part],"movimientos":[movement]})
                        batch_write(groups)
                        reset_id("arrival")
                        result(f"Recepción confirmada: {fmt(ok)} HI conformes; {fmt(reject)} rechazados; {fmt(missing)} faltantes.")
                    except Exception as exc:
                        st.error(str(exc))
    with tab3:
        pending = pending_transfer_lines(data,scope=scope)
        st.subheader("Pendientes por recibir")
        frame([{"Transferencia":r["id_transferencia"],"Origen":PLANTAS[r["planta_origen"]],
           "Destino":PLANTAS[r["planta_destino"]],"Guía":r["documento"],"Enviados":number(r["cantidad_enviada"]),
           "Procesados":r["recibido_total"],"En tránsito":r["pendiente"],"Línea":r["id_linea"]} for r in pending],340)
        st.subheader("Recepciones confirmadas")
        frame([{"Fecha":r["fecha_recepcion"],"Transferencia":r["id_transferencia"],"Conformes":number(r["cantidad_conforme"]),
          "Rechazados":number(r["cantidad_rechazada"]),"Faltantes":number(r["cantidad_faltante"]),
          "Documento":r["documento"],"Responsable":r["responsable"]} for r in data["confirmaciones"][-70:][::-1]],310)


def show_adjustment(data, scope):
    header("Bajas y ajustes", "Correcciones sustentadas documentalmente; los registros anteriores nunca se editan ni eliminan.")
    plant, wh = operation_scope(data,scope,"adjust")
    opts = asof_options(data,plant,wh,now().date())
    if not opts:
        st.info("Sin existencias en el almacén seleccionado.")
        return
    id_ = st.selectbox("Partida",[r["id_partida"] for r in opts],format_func=lambda k:label_partida(next(r for r in opts if r["id_partida"]==k)))
    part = next(r for r in opts if r["id_partida"]==id_)
    c1,c2,c3 = st.columns(3)
    kind = c1.selectbox("Movimiento",["BAJA","AJUSTE +","AJUSTE -"])
    qty = c2.number_input("Cantidad HI",min_value=1,step=1)
    date_op = c3.date_input("Fecha",now().date(),max_value=now().date())
    a,b = st.columns(2)
    doc = a.text_input("Documento / acta *")
    operator = b.text_input("Responsable *",value=st.session_state.get("operador",""))
    cause = st.selectbox("Causa *",["Diferencia de inventario","Rotura","Contaminación","Clasificación","Error de registro","Otro"])
    note = st.text_area("Justificación detallada *")
    sure = st.checkbox("Confirmo que el ajuste o baja cuenta con sustento documental")
    if st.button("Registrar ajuste/baja", type="primary",use_container_width=True):
        try:
            if not (doc.strip() and operator.strip() and note.strip() and sure):
                raise ValueError("Acta, responsable, justificación y confirmación son obligatorios.")
            fresh = read_fresh()
            p = next((x for x in fresh["partidas"] if x["id_partida"]==id_),None)
            if not p:
                raise ValueError("La partida ya no existe.")
            op = pending_id("adjust")
            require_unique(fresh,"movimientos","id_operacion",op)
            m = make_mov(op,p,kind,int(qty),date_op,doc,operator,cause=cause,obs=note)
            validate_deltas(fresh,[m])
            batch_write({"movimientos":[m]})
            reset_id("adjust")
            result(f"{kind} registrado por {fmt(qty)} HI.")
        except Exception as exc:
            st.error(str(exc))


def show_count(data, scope):
    header("Conciliación física", "El conteo registra diferencias; nunca modifica el inventario automáticamente.")
    plant, wh = operation_scope(data,scope,"count")
    opts = asof_options(data,plant,wh,now().date())
    if not opts:
        st.info("No hay partidas para conciliar.")
        return
    id_ = st.selectbox("Partida a contar",[r["id_partida"] for r in opts],
         format_func=lambda k:label_partida(next(r for r in opts if r["id_partida"]==k)))
    part = next(r for r in opts if r["id_partida"]==id_)
    st.metric("Saldo del sistema",fmt(part["saldo"]))
    with st.form("count_form"):
        count = st.number_input("Conteo físico HI",min_value=0,value=int(part["saldo"]),step=1)
        doc = st.text_input("Acta de conteo *")
        operator = st.text_input("Responsable *",value=st.session_state.get("operador",""))
        note = st.text_area("Hallazgo del conteo")
        sure = st.checkbox("Confirmo que este conteo se realizó físicamente")
        submit = st.form_submit_button("Guardar conteo",type="primary")
    if submit:
        try:
            if not (doc.strip() and operator.strip() and sure):
                raise ValueError("Completa acta, responsable y confirmación.")
            fresh = read_fresh()
            fresh_part = next(r for r in inventory(fresh) if r["id_partida"]==id_)
            if fresh_part["saldo"] != part["saldo"]:
                raise ValueError("El saldo cambió. Actualiza antes de confirmar el conteo.")
            op = pending_id("count","CNT")
            require_unique(fresh,"conteos","id_conteo",op)
            batch_write({"conteos":[fields("conteos",{"id_conteo":op,"fecha_conteo":now().date().isoformat(),
                "id_partida":id_,"saldo_sistema":part["saldo"],"conteo_fisico":int(count),
                "diferencia":int(count)-part["saldo"],"documento":doc,"responsable":operator,
                "observacion":note,"creado_en":stamp()})]})
            reset_id("count")
            result(f"Conteo registrado. Diferencia física: {int(count)-part['saldo']:+,} HI (sin ajustar stock).")
        except Exception as exc:
            st.error(str(exc))
    st.subheader("Últimos conteos")
    frame(data["conteos"][-50:][::-1],330)


def family_chain(data,pid):
    index = {p["id_partida"]:p for p in data["partidas"]}
    out, seen = [], set()
    current = pid
    while current and current in index and current not in seen:
        seen.add(current)
        out.append(index[current])
        current = txt(index[current].get("id_partida_padre"))
    return list(reversed(out))


def show_trace(data, scope):
    header("Trazabilidad integral", "Sigue cada partida desde su procedencia hasta cargas en máquinas y transferencias entre plantas.")
    inv = filtered_inventory(data,now().date(),scope)
    if not inv:
        st.info("Aún no hay partidas registradas.")
        return
    lookup = {r["id_partida"]:r for r in inv}
    needle = st.text_input("Buscar lote, documento o partida",placeholder="Ej. 237, RECP-01...")
    options = [r for r in inv if not needle or needle.casefold() in
         (r["lote"]+" "+r["documento"]+" "+r["id_partida"]).casefold()]
    if not options:
        st.info("No hay coincidencias.")
        return
    rid = st.selectbox("Partida",[r["id_partida"] for r in options],
          format_func=lambda i:label_partida(lookup[i]),key="trace_select")
    p = lookup[rid]
    a,b,c,d = st.columns(4)
    a.metric("Saldo disponible",fmt(p["saldo"]))
    b.metric("HI recibidos",fmt(p["cantidad_inicial"]))
    c.metric("Lote",p["lote"])
    d.metric("Planta",PLANTAS[p["planta"]])
    st.caption(f"Partida: {rid}  ·  Postura: {p['fecha_postura']}  ·  Documento: {p['documento']}")
    st.subheader("Cadena de procedencia")
    chain = family_chain(data,rid)
    frame([{"Paso":i+1,"Planta":PLANTAS.get(x["planta"],x["planta"]),"Lote":x["lote"],
        "Recepción":x["fecha_ingreso"],"Cantidad HI":number(x["cantidad_inicial"]),
        "Guía":x["documento"],"Partida ID":x["id_partida"]} for i,x in enumerate(chain)],240)
    st.subheader("Movimientos de la partida")
    ms = [m for m in data["movimientos"] if m["id_partida"] == rid]
    frame([{"Fecha":m["fecha_movimiento"],"Operación":m["tipo"],"Cantidad HI":number(m["cantidad"]),
      "Variación":number(m["variacion"]),"Máquina":m["id_maquina"],"Transferencia":m["id_transferencia"],
      "Documento":m["documento"],"Responsable":m["responsable"]} for m in ms],320)
    # También mostrar destinos hijos, con uno o varios traspasos posteriores.
    children = [x for x in data["partidas"] if x.get("id_partida_padre")==rid]
    if children:
        st.subheader("Partidas derivadas en otras plantas")
        frame([{"Planta":PLANTAS.get(x["planta"],x["planta"]),"Partida derivada":x["id_partida"],
          "Lote":x["lote"],"Recibidos conformes":number(x["cantidad_inicial"]),"Guía":x["documento"]} for x in children],200)
    csv_download("Exportar trazabilidad (CSV)",ms,f"trazabilidad_{rid[-8:]}.csv")


def audit_issues(data):
    issues = []
    part_ids = [p["id_partida"] for p in data["partidas"]]
    for key,n in Counter(part_ids).items():
        if n>1:
            issues.append({"Severidad":"CRÍTICA","Referencia":key,"Hallazgo":"ID de partida duplicado"})
    ids = set(part_ids)
    for r in inventory(data):
        if r["saldo"]<0:
            issues.append({"Severidad":"CRÍTICA","Referencia":r["id_partida"],"Hallazgo":"Saldo negativo"})
        if r["origen"]=="EXCEL HISTÓRICO" and r["codigo_excel"]:
            # duplicados del Excel se conservan, no se fusionan
            pass
    for m in data["movimientos"]:
        if m["id_partida"] not in ids:
            issues.append({"Severidad":"CRÍTICA","Referencia":m["id_movimiento"],"Hallazgo":"Movimiento sin partida"})
        if m["tipo"]=="CARGA" and not m["id_maquina"]:
            issues.append({"Severidad":"REVISAR","Referencia":m["id_movimiento"],"Hallazgo":"Carga sin incubadora (posible histórico)"})
        if not m["documento"]:
            issues.append({"Severidad":"REVISAR","Referencia":m["id_movimiento"],"Hallazgo":"Movimiento sin documento"})
    totals = defaultdict(int)
    for c in data["confirmaciones"]:
        totals[c["id_linea"]] += number(c["cantidad_conforme"])+number(c["cantidad_rechazada"])+number(c["cantidad_faltante"])
    for l in data["lineas"]:
        if totals[l["id_linea"]]>number(l["cantidad_enviada"]):
            issues.append({"Severidad":"CRÍTICA","Referencia":l["id_linea"],"Hallazgo":"Recepciones exceden el despacho"})
    return issues


def show_audit(data,scope):
    header("Kardex y auditoría", "Movimientos inmutables, saldos conciliados y alertas de integridad de registros.")
    tab1,tab2,tab3 = st.tabs(["Libro de movimientos","Incidencias","Conteos"])
    with tab1:
        moves = [m for m in data["movimientos"] if scope=="REG" or m["planta"]==scope]
        selection = st.selectbox("Tipo de movimiento", ["Todos"]+sorted({m["tipo"] for m in moves}))
        filtered = [m for m in moves if selection=="Todos" or m["tipo"]==selection]
        frame(filtered[-400:][::-1],525)
        csv_download("Descargar Kardex CSV",filtered,"IncubaTrack_Kardex.csv")
    with tab2:
        issues = audit_issues(data)
        if not issues:
            st.success("No se encontraron incidencias en los controles automatizados.")
        else:
            frame(issues,470)
        st.caption("La auditoría es documental. El campo Responsable se escribe manualmente hasta implementar autenticación real.")
    with tab3:
        frame(data["conteos"][-100:][::-1],460)


def show_catalogs(data,scope):
    header("Catálogos y reglas", "Configura almacenes y máquinas por planta, y valida los objetivos de antigüedad.")
    t1,t2,t3 = st.tabs(["Almacenes","Incubadoras","Parámetros"])
    with t1:
        frame([{"Planta":PLANTAS.get(w["id_planta"],w["id_planta"]),"Código":w["id_almacen"],
         "Almacén":w["nombre"],"Activo":w["activo"]} for w in data["almacenes"]],260)
        with st.form("add_wh"):
            plant = st.selectbox("Planta",list(PLANTAS),format_func=lambda p:PLANTAS[p],key="wh_pl")
            code = st.text_input("Código de almacén (único) *",placeholder="Ej. ALM-PUC-02")
            name = st.text_input("Nombre del almacén *")
            confirmed = st.checkbox("Confirmo que este almacén existe físicamente")
            submit = st.form_submit_button("Agregar almacén", type="primary")
        if submit:
            try:
                fresh=read_fresh()
                code=code.strip().upper()
                if not (code and name.strip() and confirmed):
                    raise ValueError("Código, nombre y confirmación son obligatorios.")
                require_unique(fresh,"almacenes","id_almacen",code)
                batch_write({"almacenes":[fields("almacenes",{"id_almacen":code,"id_planta":plant,
                   "nombre":name,"activo":"SI","creado_en":stamp()})]})
                result("Almacén agregado.")
            except Exception as exc: st.error(str(exc))
    with t2:
        frame([{"Planta":PLANTAS.get(m["id_planta"],m["id_planta"]),"Código":m["id_maquina"],
           "Incubadora":m["nombre"],"Activo":m["activo"]} for m in data["maquinas"]],260)
        with st.form("add_machine"):
            plant = st.selectbox("Planta",list(PLANTAS),format_func=lambda p:PLANTAS[p],key="mach_pl")
            code = st.text_input("Código real de máquina *",placeholder="Ej. PUC-INC-01")
            name = st.text_input("Descripción *",placeholder="Ej. Incubadora 1")
            confirmed = st.checkbox("Confirmo que la máquina pertenece a esta planta")
            submit=st.form_submit_button("Agregar incubadora",type="primary")
        if submit:
            try:
                fresh=read_fresh()
                code=code.strip().upper()
                if not (code and name.strip() and confirmed):
                    raise ValueError("Código, nombre y confirmación son obligatorios.")
                require_unique(fresh,"maquinas","id_maquina",code)
                batch_write({"maquinas":[fields("maquinas",{"id_maquina":code,"id_planta":plant,
                   "nombre":name,"activo":"SI","creado_en":stamp()})]})
                result("Incubadora agregada correctamente.")
            except Exception as exc: st.error(str(exc))
    with t3:
        plant = st.selectbox("Planta para los objetivos",list(PLANTAS),format_func=lambda p:PLANTAS[p])
        rules = limits(data,plant)
        st.info("Los valores 7/5/3 días provienen del Excel de Pucacaca como ejemplos. Valídalos con Incubación antes de usarlos oficialmente.")
        with st.form("set_parameters"):
            a,b,c=st.columns(3)
            n1=a.number_input("Repro <50 semanas (días)",1,30,value=rules["OBJ_MENOR_50"])
            n2=b.number_input("Repro 50-59 semanas (días)",1,30,value=rules["OBJ_50_59"])
            n3=c.number_input("Repro ≥60 semanas (días)",1,30,value=rules["OBJ_60_MAS"])
            responsible=st.text_input("Aprobado / configurado por *",value=st.session_state.get("operador",""))
            confirmed=st.checkbox("Confirmo que estos parámetros fueron validados por Incubación")
            submit=st.form_submit_button("Guardar parámetros",type="primary")
        if submit:
            try:
                if not (responsible.strip() and confirmed):
                    raise ValueError("Indica responsable y aprobación de los objetivos.")
                rows=[fields("parametros",{"id_parametro":uid("PAR"),"planta":plant,"clave":key,
                    "valor":value,"responsable":responsible,"creado_en":stamp()})
                    for key,value in (("OBJ_MENOR_50",n1),("OBJ_50_59",n2),("OBJ_60_MAS",n3))]
                batch_write({"parametros":rows})
                result("Parámetros guardados para "+PLANTAS[plant]+".")
            except Exception as exc: st.error(str(exc))


def show_import(data):
    header("Importación histórica", "Incorpora los datos anteriores a IT4_* sin sobrescribir otras hojas de Google Sheets.")
    st.warning("Usa una única fuente de apertura: Excel O versión 3.1. Si ya ingresaste datos en v4 para Pucacaca, se bloquea la migración.")
    t1,t2 = st.tabs(["Desde Excel original", "Desde IncubaTrack 3.1"])
    with t1:
        file=st.file_uploader("Archivo Control Almacen de HI DonPollo.xlsx",type=["xlsx"])
        if not file:
            st.info("Selecciona el Excel para una vista previa; no se escribirá nada hasta tu confirmación.")
            return
        try:
            blob=file.getvalue()
            if len(blob)>12_000_000:
                raise ValueError("Archivo mayor a 12 MB. Verifica su contenido.")
            plan=import_excel_plan(blob)
            a,b,c,d=st.columns(4)
            a.metric("Recepciones",len(plan["partidas"]))
            b.metric("Cargas históricas",sum(m["tipo"]=="CARGA" for m in plan["movimientos"]))
            c.metric("Ingresos HI",fmt(plan["incoming"]))
            d.metric("Saldo calculado",fmt(plan["balance"]))
            st.caption("Huella del archivo: "+plan["batch"])
            if plan["duplicates"]:
                st.warning(f"{len(plan['duplicates'])} códigos históricos se repiten. Se preservan como recepciones diferentes con IDs internos únicos.")
            for note in plan["issues"][:20]:
                st.error(note)
            if plan["issues"]:
                st.error("Hay incidencias de lectura; resuélvelas antes de aprobar una migración definitiva.")
            with st.expander("Vista previa de primeras 15 recepciones"):
                frame(plan["partidas"][:15],380)
            existing = [p for p in data["partidas"] if p["planta"]=="PUC"]
            if existing:
                st.error(f"La versión 4 ya tiene {len(existing)} recepciones de Pucacaca. Se bloquea la importación para evitar doble conteo.")
            if not plan["issues"] and not existing:
                st.info("Para el Excel validado el 03/11/2026, se esperan 227 recepciones, 8 cargas y saldo de 1 221 480 HI.")
                confirm=st.checkbox("Confirmo que este es el corte correcto y no duplica inventario existente")
                if st.button("Importar el Excel a IT4_*",type="primary",disabled=not confirm):
                    fresh=read_fresh()
                    if any(p["planta"]=="PUC" for p in fresh["partidas"]):
                        raise ValueError("Otra operación ya creó inventario de Pucacaca. No se importó.")
                    # Escritura en varias hojas en una solicitud API; no sobrescribe nada.
                    batch_write({"partidas":plan["partidas"],"movimientos":plan["movimientos"]})
                    result(f"Excel importado: {len(plan['partidas'])} partidas y {len(plan['movimientos'])} movimientos (incluidos ingresos).")
        except Exception as exc:
            st.error(f"No se pudo procesar el Excel: {exc}")

    with t2:
        st.markdown("**Migra las hojas `HI_PUC_Recepciones` y `HI_PUC_Movimientos` de la versión 3.1.**")
        st.caption("Es la opción preferible si registraste operaciones posteriores a la elaboración del Excel.")
        try:
            plan=read_legacy_v31()
            if plan is None:
                st.info("No se encontraron ambas hojas HI_PUC_* de la versión anterior en este Google Sheets.")
            elif not plan["partidas"]:
                st.info("Las hojas de la versión anterior todavía no tienen recepciones.")
            else:
                a,b,c,d=st.columns(4)
                a.metric("Recepciones",len(plan["partidas"]))
                b.metric("Movimientos",len(plan["movimientos"])-len(plan["partidas"]))
                c.metric("Ingresos",fmt(plan["incoming"]))
                d.metric("Saldo esperado",fmt(plan["balance"]))
                for issue in plan["issues"][:20]: st.error(issue)
                existing=[r for r in data["partidas"] if r["planta"]=="PUC"]
                if existing:
                    st.error(f"La versión regional ya tiene {len(existing)} recepciones Pucacaca. Se bloquea migrar nuevamente.")
                elif not plan["issues"]:
                    st.info("Los traslados antiguos, si los hay, conservarán su salida histórica sin inventar recepción en Tarapoto.")
                    confirm=st.checkbox("Confirmo que versión 3.1 contiene toda la actividad de Pucacaca y será la única fuente de apertura",key="migrate_31_ok")
                    if st.button("Migrar versión 3.1 a Regional 4.0",type="primary",disabled=not confirm):
                        fresh=read_fresh()
                        if any(r["planta"]=="PUC" for r in fresh["partidas"]):
                            raise ValueError("Ya existe inventario de Pucacaca en Regional 4.0.")
                        # Relee justo antes de guardar para evitar un corte desactualizado.
                        latest=read_legacy_v31()
                        if latest is None or latest["importacion_id"] != plan["importacion_id"]:
                            raise ValueError("Los datos de la versión 3.1 cambiaron. Actualiza y revisa nuevamente.")
                        batch_write({"partidas":latest["partidas"],"movimientos":latest["movimientos"]})
                        result(f"Migración terminada: {len(latest['partidas'])} recepciones de Pucacaca.")
        except Exception as exc:
            st.error(f"No se pudo preparar la migración de versión 3.1: {exc}")


def main():
    with st.sidebar:
        st.markdown("### 🥚 IncubaTrack")
        st.caption("REGIONAL 4.1 · DON POLLO")
        st.divider()
        scope=st.selectbox("Ámbito de visualización",["REG",*PLANTAS],
               format_func=lambda c:"Todas las plantas" if c=="REG" else PLANTAS[c])
        st.text_input("Responsable de operaciones",key="operador",placeholder="Nombre y apellido")
        st.divider()
        pages=["Centro de control","Existencias","Recepciones HI","Cargas por incubadora",
               "Transferencias","Bajas y ajustes","Conciliación física","Trazabilidad","Kardex / Auditoría",
               "Catálogos y reglas","Importación histórica"]
        page=st.radio("Navegación",pages,label_visibility="collapsed")
        st.divider()
        st.caption("Fuente: Google Sheets centralizado")
        if st.button("Actualizar datos", use_container_width=True):
            read_sheets.clear()
            st.rerun()
        st.caption("Los registros no sustituyen el control de accesos. Identificación de operadores: pendiente de implementar.")
    try:
        setup()
        data=read_sheets()
    except Exception as exc:
        header("Conexión a Google Sheets", "Estado de la conexión y lectura de datos regionales.")
        message = str(exc)
        is_quota = ("429" in message or "quota exceeded" in message.lower()
                    or "resource_exhausted" in message.lower())
        if is_quota:
            st.warning("Google Sheets alcanzó temporalmente el límite de lecturas de la cuenta de servicio.")
            st.info("Es un límite de solicitudes, no un error de credenciales ni una pérdida de inventario. "
                    "Evita actualizar repetidamente la página; la cuota se renueva por minuto. "
                    "Si otras aplicaciones usan la misma cuenta de Google Cloud, también comparten su cuota.")
            if st.button("Reintentar conexión", type="primary"):
                read_sheets.clear()
                st.rerun()
        else:
            st.error(message)
            st.caption("Revisa el SPREADSHEET_ID y los permisos de Editor del correo de servicio "
                       "solo si el error indica credenciales, permisos o acceso.")
        st.stop()
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))
    if page=="Centro de control": show_dashboard(data,scope)
    elif page=="Existencias": show_inventory(data,scope)
    elif page=="Recepciones HI": show_receipts(data,scope)
    elif page=="Cargas por incubadora": show_loads(data,scope)
    elif page=="Transferencias": show_transfers(data,scope)
    elif page=="Bajas y ajustes": show_adjustment(data,scope)
    elif page=="Conciliación física": show_count(data,scope)
    elif page=="Trazabilidad": show_trace(data,scope)
    elif page=="Kardex / Auditoría": show_audit(data,scope)
    elif page=="Catálogos y reglas": show_catalogs(data,scope)
    elif page=="Importación histórica": show_import(data)
    st.caption("Control de Gestión · IncubaTrack Regional 4.1 | Google Sheets. Uso piloto: evitar operaciones simultáneas sobre las mismas partidas.")


if __name__=="__main__":
    main()
