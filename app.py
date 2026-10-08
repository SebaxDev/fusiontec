import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
import time
from fpdf import FPDF
import io
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

# =========================================================
# COOKIE MANAGER (con fallback seguro)
# =========================================================
try:
    import extra_streamlit_components as stx
    COOKIE_AVAILABLE = True
except ImportError:
    COOKIE_AVAILABLE = False

if COOKIE_AVAILABLE:
    cookie_manager = stx.CookieManager()
else:
    cookie_manager = None

def save_cookie(key, value, days=30):
    if COOKIE_AVAILABLE and cookie_manager:
        try:
            cookie_manager.set(key, value, expires_at=datetime.now() + timedelta(days=days))
        except:
            pass

def load_cookie(key):
    if COOKIE_AVAILABLE and cookie_manager:
        try:
            return cookie_manager.get(key)
        except:
            return None
    return None

def delete_cookie(key):
    if COOKIE_AVAILABLE and cookie_manager:
        try:
            cookie_manager.delete(key)
        except:
            pass

# =========================================================
# CONFIGURACIÓN DE PÁGINA
# =========================================================
st.set_page_config(
    page_title="Fusion - App Técnicos",
    page_icon="🔧",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# =========================================================
# CSS COMPACTO
# =========================================================
st.markdown("""
<style>
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 0.5rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        padding: 0.3rem 0.5rem !important;
    }
    .stForm {
        padding: 0.3rem 0.5rem !important;
    }
    .stCaption {
        font-size: 0.78rem !important;
    }
    .element-container:has(.stMarkdown) {
        margin-bottom: -0.15rem !important;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# INYECCIÓN PWA
# =========================================================
st.markdown("""
<link rel="manifest" href="static/manifest.json">
<meta name="theme-color" content="#0e1117">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Fusion">
""", unsafe_allow_html=True)

# =========================================================
# CONFIGURACIÓN GOOGLE SHEETS Y LISTAS
# =========================================================
SHEET_ID = "13R_3Mdr25Jd-nGhK7CxdcbKkFWLc0LPdYrOLOY8sZJo"

WORKSHEET_RECLAMOS = "Reclamos"
WORKSHEET_CLIENTES = "Clientes"
WORKSHEET_USUARIOS = "usuarios"
WORKSHEET_NOVEDADES = "Novedades"
WORKSHEET_CAJAS = "Cajas"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Listas Globales
TECNICOS_DISPONIBLES = [
    "BLUME", "CONEJO", "GABRIEL", "JUAN", "JUNIOR", "MAXI", "MARKI",
    "PEDRITO", "RAMON", "RENE", "ROQUE", "VIKI", "OFICINA", "BASE"
]
SECTORES_DISPONIBLES = [str(n) for n in range(1, 18)]
SPLITTERS_DISPONIBLES = ["1/4", "1/8", "1/16"]
MARCAS_EQUIPO = ["Huawei", "VSol"]

# =========================================================
# ESCUDOS ANTI-BLOQUEO (TENACITY)
# =========================================================
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=10))
def safe_get_all_records(worksheet):
    return worksheet.get_all_records()

@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=10))
def safe_batch_update(worksheet, updates):
    return worksheet.batch_update(updates)

@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=10))
def safe_update_cell(worksheet, row, col, val):
    return worksheet.update_cell(row, col, val)

@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=10))
def safe_append_row(worksheet, row_data):
    return worksheet.append_row(row_data)

# Wrappers para compatibilidad con lógica de Cajas NAP
def _do_batch_update(ws, upd):
    try:
        safe_batch_update(ws, upd)
        return True, None
    except Exception as e:
        return False, str(e)

def _do_append(ws, row):
    try:
        safe_append_row(ws, row)
        return True, None
    except Exception as e:
        return False, str(e)

# =========================================================
# NOMBRES DE COLUMNAS EN HOJA CLIENTES
# =========================================================
COL_CLIENTE_PRECINTO = 'N° de Precinto'
COL_CLIENTE_CAJA = 'Caja NAP'
COL_CLIENTE_OBS = 'Observaciones'
COL_CLIENTE_LAT = 'Latitud'
COL_CLIENTE_LON = 'Longitud'

# =========================================================
# CONEXIÓN GOOGLE SHEETS
# =========================================================
@st.cache_resource(show_spinner="Conectando...")
def init_google_sheets():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SHEET_ID)
        ws_reclamos = spreadsheet.worksheet(WORKSHEET_RECLAMOS)
        ws_clientes = spreadsheet.worksheet(WORKSHEET_CLIENTES)
        ws_usuarios = spreadsheet.worksheet(WORKSHEET_USUARIOS)
        ws_cajas = spreadsheet.worksheet(WORKSHEET_CAJAS)

        try:
            ws_novedades = spreadsheet.worksheet(WORKSHEET_NOVEDADES)
        except gspread.exceptions.WorksheetNotFound:
            ws_novedades = spreadsheet.add_worksheet(title=WORKSHEET_NOVEDADES, rows=10, cols=2)
            ws_novedades.update('A1:B1', [['Fecha', 'Mensaje']])

        return ws_reclamos, ws_clientes, ws_usuarios, ws_novedades, ws_cajas
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        st.stop()

# =========================================================
# RESOLVER ÍNDICES DE COLUMNAS UNA SOLA VEZ
# =========================================================
def resolver_col_indices_clientes(ws_clientes):
    if 'clientes_col_idx' in st.session_state:
        return st.session_state['clientes_col_idx']

    result = {'precinto': None, 'caja': None, 'obs': None, 'lat': None, 'lon': None}
    try:
        headers = ws_clientes.row_values(1)
        headers = [h.strip() for h in headers]
        if COL_CLIENTE_PRECINTO in headers:
            result['precinto'] = headers.index(COL_CLIENTE_PRECINTO) + 1
        if COL_CLIENTE_CAJA in headers:
            result['caja'] = headers.index(COL_CLIENTE_CAJA) + 1
        if COL_CLIENTE_OBS in headers:
            result['obs'] = headers.index(COL_CLIENTE_OBS) + 1
        if COL_CLIENTE_LAT in headers:
            result['lat'] = headers.index(COL_CLIENTE_LAT) + 1
        if COL_CLIENTE_LON in headers:
            result['lon'] = headers.index(COL_CLIENTE_LON) + 1
    except Exception as e:
        st.warning(f"No se pudieron leer headers de Clientes: {e}")

    st.session_state['clientes_col_idx'] = result
    return result

# =========================================================
# FUNCIONES HELPER BIDIRECCIONALES (CLIENTE <-> CAJA)
# =========================================================
def verificar_precinto_duplicado(df_clientes, precinto, cliente_id_ignorar=None):
    if not precinto or pd.isna(precinto) or str(precinto).strip() == "":
        return None
    df_filtro = df_clientes[df_clientes["N° de Precinto"].astype(str).str.strip() == str(precinto).strip()]
    if cliente_id_ignorar:
        df_filtro = df_filtro[df_filtro["Nº Cliente"].astype(str).str.strip() != str(cliente_id_ignorar).strip()]
    if not df_filtro.empty:
        return df_filtro.iloc[0]
    return None

def _obtener_info_caja(df_cajas, nombre_caja):
    if df_cajas is None or df_cajas.empty or not nombre_caja or str(nombre_caja).strip() == "":
        return None
    caja_data = df_cajas[df_cajas["N De Caja"].astype(str).str.strip() == str(nombre_caja).strip()]
    if caja_data.empty:
        return None
    return caja_data.iloc[0]

def _buscar_puerto_vacio(caja_row):
    splitter = str(caja_row.get("Splitter", "1/4")).strip()
    num_puertos = 4
    if splitter == "1/8": num_puertos = 8
    elif splitter == "1/16": num_puertos = 16
    letras = ["I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X"]
    for i in range(num_puertos):
        val = str(caja_row.get(f"Precinto {i+1}", "")).strip()
        if val in ("", "nan", "None"):
            return letras[i]
    return None

def _buscar_puerto_ocupado(caja_row, precinto):
    if not precinto or str(precinto).strip() == "":
        return None
    splitter = str(caja_row.get("Splitter", "1/4")).strip()
    num_puertos = 4
    if splitter == "1/8": num_puertos = 8
    elif splitter == "1/16": num_puertos = 16
    letras = ["I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X"]
    for i in range(num_puertos):
        val = str(caja_row.get(f"Precinto {i+1}", "")).strip()
        if val == str(precinto).strip():
            return letras[i]
    return None

# =========================================================
# CARGA DE DATOS SEGUROS
# =========================================================
@st.cache_data(ttl=120)
def cargar_datos():
    ws_reclamos, ws_clientes, ws_usuarios, ws_novedades, ws_cajas = init_google_sheets()
    
    # Lecturas blindadas
    df_reclamos = pd.DataFrame(safe_get_all_records(ws_reclamos))
    df_clientes = pd.DataFrame(safe_get_all_records(ws_clientes))
    df_usuarios = pd.DataFrame(safe_get_all_records(ws_usuarios))
    df_cajas_raw = pd.DataFrame(safe_get_all_records(ws_cajas))

    df_reclamos.columns = df_reclamos.columns.str.strip()
    df_clientes.columns = df_clientes.columns.str.strip()
    df_usuarios.columns = df_usuarios.columns.str.strip()

    try:
        df_novedades = pd.DataFrame(safe_get_all_records(ws_novedades))
        df_novedades.columns = df_novedades.columns.str.strip()
    except:
        df_novedades = pd.DataFrame(columns=['Fecha', 'Mensaje'])

    df_clientes_raw = df_clientes.copy()

    df_c = df_clientes.rename(columns={
        'Nº Cliente': 'nro_cliente_cli',
        'Latitud': 'lat',
        'Longitud': 'lon',
        'N° de Precinto': 'precinto_cliente',
        'Caja NAP': 'caja_nap'
    })
    df_c['nro_cliente_cli'] = df_c['nro_cliente_cli'].astype(str)

    if 'lat' in df_c.columns:
        df_c['lat'] = pd.to_numeric(df_c['lat'].astype(str).str.replace(',', '.'), errors='coerce')
    if 'lon' in df_c.columns:
        df_c['lon'] = pd.to_numeric(df_c['lon'].astype(str).str.replace(',', '.'), errors='coerce')

    if 'precinto_cliente' in df_c.columns:
        df_c['precinto_cliente'] = df_c['precinto_cliente'].replace(['*', '', ' '], np.nan)

    plan_col_name = next((c for c in df_c.columns if 'plan' in str(c).lower()), None)
    
    cols_cliente = ['nro_cliente_cli', 'lat', 'lon', 'precinto_cliente', 'caja_nap']
    if plan_col_name:
        df_c['Plan_Limpio'] = df_c[plan_col_name].astype(str).replace(['nan', 'None', '', ' ', '*'], np.nan)
        cols_cliente.append('Plan_Limpio')

    datos_cliente = df_c[cols_cliente].drop_duplicates(subset=['nro_cliente_cli'])

    df_r = df_reclamos.copy()
    df_r['Nº Cliente'] = df_r['Nº Cliente'].astype(str)
    df_r = df_r.merge(datos_cliente, left_on='Nº Cliente', right_on='nro_cliente_cli', how='left')

    tz_argentina = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_argentina)
    df_r['Fecha_Parseada'] = pd.to_datetime(df_r['Fecha y hora'], format='%d/%m/%Y %H:%M', errors='coerce')
    df_r['Fecha_Parseada'] = df_r['Fecha_Parseada'].dt.tz_localize(tz_argentina)
    df_r['Horas_Transcurridas'] = (ahora - df_r['Fecha_Parseada']).dt.total_seconds() / 3600

    df_r['Estado_Limpio'] = df_r['Estado'].astype(str).str.strip()
    df_r['Tecnico_Limpio'] = df_r['Técnico'].astype(str).str.strip()
    df_r['Tecnico_Limpio'] = df_r['Tecnico_Limpio'].replace('', np.nan)

    return df_r, df_usuarios, df_clientes_raw, df_novedades, df_cajas_raw

# =========================================================
# FUNCIÓN PARA DIBUJAR TARJETAS
# =========================================================
def renderizar_tarjeta(row, df_reclamos, ws_reclamos, es_admin=False,
                       ws_clientes=None, df_clientes_raw=None,
                       clientes_col_idx=None, modo="en_curso",
                       ws_cajas=None, df_cajas_raw=None):
    if clientes_col_idx is None:
        clientes_col_idx = {'precinto': None, 'caja': None, 'obs': None, 'lat': None, 'lon': None}

    sheet_row_num = row.name + 2
    horas = row['Horas_Transcurridas']

    badge = "🟢 Normal"
    badge_color = "#4caf50"
    if pd.notna(horas):
        if horas >= 48:
            badge = "🔴 +48hs"
            badge_color = "#f44336"
        elif horas >= 24:
            badge = "🟡 +24hs"
            badge_color = "#ff9800"

    direccion = str(row.get('Dirección', '')) if pd.notna(row.get('Dirección')) else ''
    telefono = str(row.get('Teléfono', '')) if pd.notna(row.get('Teléfono')) else ''
    tipo_reclamo = str(row.get('Tipo de reclamo', ''))
    detalles = str(row.get('Detalles', '')) if pd.notna(row.get('Detalles')) and str(row.get('Detalles')) not in ['nan', '*', ''] else ''
    sector = str(row.get('Sector', '')) if pd.notna(row.get('Sector')) else ''
    nombre_cliente = str(row.get('Nombre', ''))
    nro_cliente = str(row.get('Nº Cliente', ''))
    tecnico = str(row.get('Tecnico_Limpio', '')) if pd.notna(row.get('Tecnico_Limpio')) and str(row.get('Tecnico_Limpio')) not in ['nan', ''] else ''

    precinto = ''
    if pd.notna(row.get('precinto_cliente')) and str(row.get('precinto_cliente')) not in ['nan', '*', '', ' ']:
        precinto = str(row.get('precinto_cliente'))
        
    caja_nap = ''
    if pd.notna(row.get('caja_nap')) and str(row.get('caja_nap')) not in ['nan', 'None', '', ' ']:
        caja_nap = str(row.get('caja_nap'))

    if pd.notna(horas):
        if horas < 1:
            texto_tiempo = f"{int(horas * 60)}min"
        elif horas < 24:
            texto_tiempo = f"{int(horas)}hs"
        else:
            texto_tiempo = f"{int(horas / 24)}d"
    else:
        texto_tiempo = "?"

    tiene_ubicacion = pd.notna(row.get('lat')) and pd.notna(row.get('lon'))
    maps_url = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}" if tiene_ubicacion else None

    cliente_fila = None
    cliente_match = None
    if ws_clientes is not None and df_clientes_raw is not None:
        df_cl = df_clientes_raw.copy()
        df_cl['Nº Cliente'] = df_cl['Nº Cliente'].astype(str).str.strip()
        cliente_match = df_cl[df_cl['Nº Cliente'] == nro_cliente]
        if not cliente_match.empty:
            cliente_fila = cliente_match.index[0] + 2

    col_precinto_idx = clientes_col_idx.get('precinto')
    col_caja_idx = clientes_col_idx.get('caja')
    col_lat_idx = clientes_col_idx.get('lat')
    col_lon_idx = clientes_col_idx.get('lon')
    col_obs_idx = clientes_col_idx.get('obs')

    with st.container(border=True):
        tecnico_html = f" <small style='color:#888;'>👷{tecnico}</small>" if (es_admin and tecnico) else ""
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-size:1.05em;'><b>🎫 {nro_cliente}</b> — {nombre_cliente}{tecnico_html}</span>"
            f"<span style='color:{badge_color};font-weight:bold;font-size:0.82em;'>{badge} · {texto_tiempo}</span>"
            f"</div>",
            unsafe_allow_html=True
        )

        info_parts = []
        if sector:
            info_parts.append(f"📍{sector}")
        if tipo_reclamo:
            info_parts.append(f"⚙️{tipo_reclamo}")
        if info_parts:
            st.markdown(" · ".join(info_parts))

        contact_parts = []
        if direccion:
            contact_parts.append(f"🏠{direccion}")
        if telefono:
            contact_parts.append(f"📞{telefono}")
        if contact_parts:
            st.markdown(" · ".join(contact_parts))

        loc_parts = []
        if precinto:
            loc_parts.append(f"🔒{precinto}")
        else:
            loc_parts.append("🔒<i style='color:#888;'>Sin precinto</i>")
            
        if caja_nap:
            loc_parts.append(f"📦{caja_nap}")
        else:
            loc_parts.append("📦<i style='color:#888;'>Sin caja</i>")

        if tiene_ubicacion and maps_url:
            loc_parts.append(f"<a href='{maps_url}' target='_blank' style='color:#00a8ff;text-decoration:none;'>📍Maps</a>")
        else:
            loc_parts.append("<i style='color:#888;'>📍Sin geo</i>")

        st.markdown(" · ".join(loc_parts), unsafe_allow_html=True)

        if detalles:
            st.caption(f"📝 {detalles}")

        if es_admin and cliente_fila is not None:
            with st.expander("✏️ Editar Precinto / Caja / Coordenadas"):
                col_edit1, col_edit2 = st.columns(2)

                with col_edit1:
                    # ----- FORMULARIO DE PRECINTO Y CAJA (CON LOGICA BIDIRECCIONAL BLINDADA) -----
                    caja_actual = caja_nap.strip()
                    opciones_cajas = [""]
                    if df_cajas_raw is not None and not df_cajas_raw.empty:
                        cajas_validas = [str(c).strip() for c in df_cajas_raw["N De Caja"].dropna().tolist() if str(c).strip() not in ("", "nan", "None")]
                        opciones_cajas.extend(sorted(list(set(cajas_validas))))
                        
                    if caja_actual and caja_actual not in opciones_cajas:
                        opciones_cajas.append(caja_actual)
                        
                    try:
                        caja_idx = opciones_cajas.index(caja_actual)
                    except:
                        caja_idx = 0

                    with st.form(f"form_datos_edit_{nro_cliente}_{sheet_row_num}"):
                        new_precinto = st.text_input("Precinto", value=precinto if precinto else "")
                        new_caja = st.selectbox("Caja NAP", options=opciones_cajas, index=caja_idx)
                        
                        submit_datos = st.form_submit_button("💾 Guardar Datos")
                        if submit_datos:
                            precinto_limpio = new_precinto.strip()
                            caja_limpia = new_caja.strip()
                            
                            duplicado = verificar_precinto_duplicado(df_clientes_raw, precinto_limpio, nro_cliente)
                            if duplicado is not None:
                                st.error(f"❌ El precinto '{precinto_limpio}' ya está usado por el cliente: {duplicado['Nº Cliente']} - {duplicado['Nombre']}")
                            else:
                                updates_caja = []
                                caja_llena_error = False

                                if (caja_actual != caja_limpia) or (precinto != precinto_limpio):
                                    # 1. Quitar precinto viejo de la caja vieja
                                    if caja_actual and precinto:
                                        c_row_v = _obtener_info_caja(df_cajas_raw, caja_actual)
                                        if c_row_v is not None:
                                            p_ocup = _buscar_puerto_ocupado(c_row_v, precinto)
                                            if p_ocup:
                                                updates_caja.append({"range": f"{p_ocup}{c_row_v.name + 2}", "values": [[""]]})
                                    
                                    # 2. Agregar precinto nuevo a la caja nueva
                                    if caja_limpia and precinto_limpio:
                                        c_row_n = _obtener_info_caja(df_cajas_raw, caja_limpia)
                                        if c_row_n is not None:
                                            p_vac = _buscar_puerto_vacio(c_row_n)
                                            if p_vac:
                                                updates_caja.append({"range": f"{p_vac}{c_row_n.name + 2}", "values": [[precinto_limpio]]})
                                            else:
                                                caja_llena_error = True
                                                st.error(f"❌ La Caja NAP '{caja_limpia}' ya está llena.")

                                if not caja_llena_error:
                                    updates_clientes = []
                                    if col_precinto_idx and (precinto != precinto_limpio):
                                        updates_clientes.append({"range": gspread.utils.rowcol_to_a1(cliente_fila, col_precinto_idx), "values": [[precinto_limpio]]})
                                    if col_caja_idx and (caja_actual != caja_limpia):
                                        updates_clientes.append({"range": gspread.utils.rowcol_to_a1(cliente_fila, col_caja_idx), "values": [[caja_limpia]]})
                                    
                                    try:
                                        if updates_clientes:
                                            safe_batch_update(ws_clientes, updates_clientes)
                                        if updates_caja and ws_cajas is not None:
                                            safe_batch_update(ws_cajas, updates_caja)
                                            
                                        if updates_clientes or updates_caja:
                                            st.cache_data.clear()
                                            st.success("✅ Datos y Red actualizados")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.info("ℹ️ No hay cambios para guardar.")
                                    except Exception as e:
                                        st.error(f"❌ {e}")

                with col_edit2:
                    # ----- FORMULARIO DE COORDENADAS -----
                    lat_val = ""
                    lon_val = ""
                    if tiene_ubicacion:
                        lat_val = str(row.get('lat', ''))
                        lon_val = str(row.get('lon', ''))
                    elif cliente_match is not None and not cliente_match.empty:
                        lat_raw = str(cliente_match.iloc[0].get('Latitud', '')).strip()
                        lon_raw = str(cliente_match.iloc[0].get('Longitud', '')).strip()
                        lat_val = lat_raw if lat_raw not in ("nan", "None", "") else ""
                        lon_val = lon_raw if lon_raw not in ("nan", "None", "") else ""

                    with st.form(f"form_geo_edit_{nro_cliente}_{sheet_row_num}"):
                        new_lat = st.text_input(
                            "Lat", value=lat_val,
                            placeholder="-26.xxxxxx",
                            key=f"lt_edit_{nro_cliente}_{sheet_row_num}"
                        )
                        new_lon = st.text_input(
                            "Lon", value=lon_val,
                            placeholder="-59.xxxxxx",
                            key=f"ln_edit_{nro_cliente}_{sheet_row_num}"
                        )
                        submit_g = st.form_submit_button("💾 Guardar Ubicación")
                        if submit_g:
                            if not new_lat.strip() or not new_lon.strip():
                                st.error("❌ Completá ambos campos")
                            else:
                                try:
                                    float(new_lat.strip().replace(',', '.'))
                                    float(new_lon.strip().replace(',', '.'))
                                    if col_lat_idx and col_lon_idx:
                                        updates = [
                                            {"range": gspread.utils.rowcol_to_a1(cliente_fila, col_lat_idx), "values": [[new_lat.strip()]]},
                                            {"range": gspread.utils.rowcol_to_a1(cliente_fila, col_lon_idx), "values": [[new_lon.strip()]]}
                                        ]
                                        safe_batch_update(ws_clientes, updates)
                                        st.cache_data.clear()
                                        st.success("✅ Coordenadas actualizadas")
                                        time.sleep(0.8)
                                        st.rerun()
                                    else:
                                        st.error("❌ Columnas de lat/lon no encontradas en hoja")
                                except ValueError:
                                    st.error("❌ Coordenadas deben ser numéricas")
                                except Exception as e:
                                    st.error(f"❌ {e}")

        if modo == "en_curso":
            with st.form(f"form_verify_{sheet_row_num}"):
                obs = st.text_input(
                    "📝 Obs", placeholder="Ej: Caja con mala señal",
                    key=f"obs_{sheet_row_num}"
                )
                submit_verify = st.form_submit_button("✅ Verificar", use_container_width=True)

                if submit_verify:
                    try:
                        col_idx = df_reclamos.columns.get_loc('Estado') + 1
                        safe_update_cell(ws_reclamos, sheet_row_num, col_idx, "Verificado")

                        if obs.strip() and cliente_fila is not None and col_obs_idx:
                            tz_arg = timezone(timedelta(hours=-3))
                            ahora = datetime.now(tz_arg)
                            fecha_obs = f"{ahora.day}/{ahora.month}/{ahora.year}"
                            obs_text = f"{fecha_obs}: {obs.strip().upper()}"

                            current_val = safe_get_all_records(ws_clientes)[cliente_fila-2].get(COL_CLIENTE_OBS, "")
                            new_val = (str(current_val).strip() + "\n" + obs_text) if str(current_val).strip() else obs_text
                            safe_update_cell(ws_clientes, cliente_fila, col_obs_idx, new_val)

                        st.cache_data.clear()
                        st.success("¡Verificado!")
                        time.sleep(0.8)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        elif modo == "pendiente" and es_admin:
            with st.form(f"form_asignar_{nro_cliente}_{sheet_row_num}"):
                tecnicos_sel = st.multiselect(
                    "👷 Técnico(s)", TECNICOS_DISPONIBLES,
                    key=f"ms_tec_{nro_cliente}_{sheet_row_num}"
                )
                submit_asignar = st.form_submit_button("🚀 Asignar → En Curso", use_container_width=True)

                if submit_asignar:
                    if not tecnicos_sel:
                        st.error("❌ Seleccioná al menos un técnico.")
                    else:
                        try:
                            col_estado = df_reclamos.columns.get_loc('Estado') + 1
                            col_tecnico = df_reclamos.columns.get_loc('Técnico') + 1
                            tecnicos_str = ", ".join(tecnicos_sel)

                            updates = [
                                {"range": gspread.utils.rowcol_to_a1(sheet_row_num, col_estado), "values": [["En curso"]]},
                                {"range": gspread.utils.rowcol_to_a1(sheet_row_num, col_tecnico), "values": [[tecnicos_str]]}
                            ]
                            safe_batch_update(ws_reclamos, updates)

                            mensaje_whatsapp = generar_mensaje_asignacion(row, tecnicos_str)
                            st.session_state["mensaje_para_copiar"] = mensaje_whatsapp

                            st.cache_data.clear()
                            st.success(f"✅ Asignado a **{tecnicos_str}**")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {e}")

# =========================================================
# BUSCADOR DE RECLAMOS
# =========================================================
def filtrar_por_busqueda(df, query):
    if not query or not query.strip():
        return df

    q = query.strip().lower()
    search_cols = ['Nº Cliente', 'Nombre', 'Dirección', 'Sector', 'Tipo de reclamo', 'Tecnico_Limpio']
    search_cols = [c for c in search_cols if c in df.columns]

    if not search_cols:
        return df

    mask = pd.Series(False, index=df.index)
    for col in search_cols:
        mask = mask | df[col].astype(str).str.lower().str.contains(q, na=False)

    return df[mask]

# =========================================================
# GENERADOR DE PDF (Resumen por Técnico)
# =========================================================
class PDFReporte(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, f'Resumen de los Trabajos del Día - {datetime.now().strftime("%d/%m/%Y")}', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf(df, fecha_str):
    pdf = PDFReporte('P', 'mm', 'A4')
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    col_width = 90
    margin_x = 10
    margin_y = 20
    bottom_limit = 275
    gap = 10
    cols_x = [margin_x, margin_x + col_width + gap]

    current_col = 0
    current_x = cols_x[current_col]
    current_y = margin_y

    df['Tecnico_Grupo'] = df['Tecnico_Limpio'].fillna('Sin Asignar')
    tecnicos = sorted(df['Tecnico_Grupo'].unique())

    for tecnico in tecnicos:
        df_tec = df[df['Tecnico_Grupo'] == tecnico]
        count_tec = len(df_tec)
        count_ok = len(df_tec[df_tec['Estado_Limpio'] == 'Verificado'])
        count_pendientes = count_tec - count_ok
        block_height = 7 + (count_tec * 5)

        if current_y + block_height > bottom_limit:
            current_col += 1
            if current_col > 1:
                pdf.add_page()
                current_col = 0
            current_x = cols_x[current_col]
            current_y = margin_y

        tecnico_safe = tecnico.encode('latin-1', 'replace').decode('latin-1')
        tecnico_display = tecnico_safe.title()

        pdf.set_xy(current_x, current_y)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(col_width, 5, f"Técnico: {tecnico_display} ({count_tec}) ({count_ok} OK - {count_pendientes} Pendientes)", 0, 1)
        pdf.line(current_x, current_y + 5, current_x + col_width, current_y + 5)
        current_y += 7

        for idx, row in df_tec.iterrows():
            if current_y > bottom_limit:
                current_col += 1
                if current_col > 1:
                    pdf.add_page()
                    current_col = 0
                current_x = cols_x[current_col]
                current_y = margin_y

            status = "OK" if row['Estado_Limpio'] == "Verificado" else "Pendiente"
            nro_cliente_safe = str(row['Nº Cliente']).encode('latin-1', 'replace').decode('latin-1')
            tipo_safe = str(row.get('Tipo de reclamo', '')).encode('latin-1', 'replace').decode('latin-1')

            pdf.set_xy(current_x, current_y)
            pdf.set_font('Helvetica', '', 8)
            parte1 = f"{nro_cliente_safe} - "
            w1 = pdf.get_string_width(parte1)
            pdf.cell(w1, 4, parte1, 0, 0)

            pdf.set_font('Helvetica', 'B', 8)
            w2 = pdf.get_string_width(status)
            pdf.cell(w2, 4, status, 0, 0)

            pdf.set_font('Helvetica', '', 8)
            parte3 = f" - {tipo_safe}"
            w3 = col_width - w1 - w2

            if pdf.get_string_width(parte3) > w3:
                while pdf.get_string_width(parte3 + "..") > w3 and len(parte3) > 4:
                    parte3 = parte3[:-1]
                parte3 = parte3.rstrip(' -.') + ".."

            pdf.cell(w3, 4, parte3, 0, 1)
            current_y += 5

    return bytes(pdf.output())

# =========================================================
# GENERADOR DE PDF VERIFICADOS DETALLADO
# =========================================================
class PDFVerificados(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 11)
        self.cell(0, 8, f'Trabajos Verificados - {datetime.now().strftime("%d/%m/%Y")}', 0, 1, 'C')
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}}', 0, 0, 'C')

def generar_pdf_verificados_detallado(df_verificados):
    pdf = PDFVerificados('P', 'mm', 'A4')
    pdf.set_auto_page_break(auto=False)
    pdf.alias_nb_pages()
    pdf.add_page()

    margin_x = 10
    page_width = 210
    usable_width = page_width - (margin_x * 2)
    content_start_y = 25
    footer_zone_y = 282
    row_height = 6
    header_height = 7

    col_widths = [22, 48, 55, 30, 35]
    col_headers = ['Nº Cliente', 'Nombre', 'Tipo de Reclamo', 'Precinto', 'Tecnico']

    col_x = [margin_x]
    for w in col_widths[:-1]:
        col_x.append(col_x[-1] + w)

    def dibujar_encabezado_tabla(y_pos):
        pdf.set_font('Helvetica', 'B', 7.5)
        pdf.set_fill_color(50, 50, 50)
        pdf.set_text_color(255, 255, 255)
        for i, header in enumerate(col_headers):
            header_safe = header.encode('latin-1', 'replace').decode('latin-1')
            pdf.set_xy(col_x[i], y_pos)
            pdf.cell(col_widths[i], header_height, header_safe, 1, 0, 'C', fill=True)
        pdf.set_text_color(0, 0, 0)
        return y_pos + header_height

    current_y = content_start_y
    pdf.set_xy(margin_x, current_y)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(usable_width, 6, f'Total de trabajos verificados: {len(df_verificados)}', 0, 1, 'L', fill=True)
    current_y += 8
    current_y = dibujar_encabezado_tabla(current_y)

    pdf.set_font('Helvetica', '', 7)
    fila_num = 0

    for idx, row in df_verificados.iterrows():
        if current_y + row_height > footer_zone_y:
            pdf.add_page()
            current_y = content_start_y
            current_y = dibujar_encabezado_tabla(current_y)

        nro_cliente = str(row.get('Nº Cliente', '')).encode('latin-1', 'replace').decode('latin-1')
        nombre = str(row.get('Nombre', '')).encode('latin-1', 'replace').decode('latin-1')
        tipo_reclamo = str(row.get('Tipo de reclamo', '')).encode('latin-1', 'replace').decode('latin-1')

        precinto_raw = row.get('precinto_cliente', '')
        if pd.notna(precinto_raw) and str(precinto_raw) not in ['nan', '*', '', ' ']:
            precinto = str(precinto_raw).encode('latin-1', 'replace').decode('latin-1')
        else:
            precinto = '-'

        tecnico_raw = row.get('Tecnico_Limpio', '')
        if pd.notna(tecnico_raw) and str(tecnico_raw).strip() not in ['nan', '', ' ']:
            tecnico = str(tecnico_raw).encode('latin-1', 'replace').decode('latin-1')
        else:
            tecnico = 'Sin asignar'

        datos = [nro_cliente, nombre, tipo_reclamo, precinto, tecnico]

        if fila_num % 2 == 0:
            pdf.set_fill_color(255, 255, 255)
        else:
            pdf.set_fill_color(242, 242, 242)

        for i, dato in enumerate(datos):
            ancho_celda = col_widths[i] - 2
            if pdf.get_string_width(dato) > ancho_celda:
                while pdf.get_string_width(dato + "..") > ancho_celda and len(dato) > 3:
                    dato = dato[:-1]
                dato = dato.rstrip(' .-,') + ".."
            pdf.set_xy(col_x[i] + 1, current_y)
            pdf.cell(col_widths[i] - 2, row_height, dato, 1, 0, 'L', fill=True)

        current_y += row_height
        fila_num += 1

    if current_y + 10 > footer_zone_y:
        pdf.add_page()
        current_y = content_start_y

    current_y += 3
    pdf.set_xy(margin_x, current_y)
    pdf.set_font('Helvetica', 'I', 7)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(
        usable_width, 5,
        f'Documento generado el {datetime.now().strftime("%d/%m/%Y a las %H:%M")} - Fusion App Tecnicos',
        0, 1, 'C'
    )

    return bytes(pdf.output())

# =========================================================
# GENERADOR DE MENSAJE WHATSAPP
# =========================================================
def generar_mensaje_asignacion(row, tecnicos_asignados):
    cliente = str(row.get('Nombre', 'Sin Nombre'))
    nro_cliente = str(row.get('Nº Cliente', ''))
    direccion = str(row.get('Dirección', 'Sin dirección'))
    telefono = str(row.get('Teléfono', 'Sin teléfono'))
    plan = str(row.get('Plan_Limpio', '')) 
    tipo_reclamo = str(row.get('Tipo de reclamo', ''))
    detalles = str(row.get('Detalles', ''))
    sector = str(row.get('Sector', ''))

    if detalles == '*' or detalles == 'nan':
        detalles = ""

    precinto = ''
    if pd.notna(row.get('precinto_cliente')) and str(row.get('precinto_cliente')) not in ['nan', '*', '']:
        precinto = str(row.get('precinto_cliente'))
        
    caja_nap = str(row.get('caja_nap', '')).replace('nan', '').strip()

    sep = "------------------------------------------------"

    msg = f"🔧 *NUEVA ASIGNACIÓN DE TRABAJO* 🔧\n"
    msg += sep + "\n"
    msg += f"👷 *TÉCNICO(S):* {tecnicos_asignados}\n"
    msg += f"👤 *CLIENTE:* {cliente} (Nº {nro_cliente})\n"
    if sector:
        msg += f"📍 *SECTOR:* {sector}\n"
    msg += f"🏠 *DIRECCIÓN:* {direccion}\n"
    
    if telefono and telefono != 'Sin teléfono':
        msg += f"📞 *TEL:* {telefono}\n"
        
    if plan and plan.lower() not in ['nan', 'none', '', '*', ' ']:
        msg += f"📄 *PLAN:* {plan}\n"
        
    if precinto:
        msg += f"🔒 *PRECINTO:* {precinto}\n"
    else:
        msg += f"🔒 *PRECINTO:* No cuenta con número de precinto\n"
        
    if caja_nap and caja_nap.lower() != 'none':
        msg += f"📦 *CAJA NAP:* {caja_nap}\n"
        
    msg += sep + "\n"
    msg += f"⚙️ *RECLAMO:* {tipo_reclamo}\n"
    if detalles:
        msg += f"📝 *DETALLE:* {detalles}\n"

    tiene_ubicacion = pd.notna(row.get('lat')) and pd.notna(row.get('lon'))
    if tiene_ubicacion:
        maps_link = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}"
        msg += sep + "\n"
        msg += f"🗺️ *UBICACIÓN:* {maps_link}\n"
        msg += "(Click en el link para abrir Google Maps)"
    else:
        msg += sep + "\n"
        msg += "⚠️ *Sin georeferenciación exacta*"

    return msg

# =========================================================
# LOGIN
# =========================================================
def login_screen():
    st.title("🔧 Fusion App Técnicos")
    st.write("Ingresá tus credenciales para ver tus reclamos asignados.")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Ingresar", use_container_width=True)

        if submit:
            try:
                ws_reclamos, ws_clientes, ws_usuarios, ws_novedades, ws_cajas = init_google_sheets()
                df_usuarios = pd.DataFrame(safe_get_all_records(ws_usuarios))

                user_row = df_usuarios[(df_usuarios['username'] == username) & (df_usuarios['password'] == password)]

                if not user_row.empty:
                    rol = str(user_row.iloc[0]['rol']).strip()
                    rol_lower = rol.lower()
                    es_admin = rol_lower in ['admin', 'oficina', 'supervisor']

                    st.session_state["authenticated"] = True
                    st.session_state["user_name"] = user_row.iloc[0]['nombre']
                    st.session_state["rol"] = rol
                    st.session_state["es_admin"] = es_admin

                    save_cookie("fusion_user", username, days=30)
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
            except Exception as e:
                st.error(f"Error al cargar datos: {e}")

# =========================================================
# APP PRINCIPAL
# =========================================================
def main_app():
    es_admin = st.session_state.get('es_admin', False)
    rol = st.session_state.rol

    # --- Header compacto ---
    col1, col2, col3 = st.columns([4, 1, 1])
    with col1:
        st.markdown(f"### 👷 {st.session_state.user_name} ({'Admin' if es_admin else 'Técnico'})")
    with col2:
        if st.button("🔄", help="Refrescar datos"):
            st.cache_data.clear()
            # Limpiar índices cacheados para que se re-resuelvan
            if 'clientes_col_idx' in st.session_state:
                del st.session_state['clientes_col_idx']
            st.rerun()
    with col3:
        if st.button("🚪", help="Salir"):
            delete_cookie("fusion_user")
            st.session_state.authenticated = False
            st.rerun()

    st.divider()

    df_reclamos, _, df_clientes_raw, df_novedades, df_cajas_raw = cargar_datos()
    ws_reclamos, ws_clientes, _, ws_novedades, ws_cajas = init_google_sheets()

    # ═══════════════════════════════════════════════════════
    # RESOLVER ÍNDICES DE COLUMNAS UNA SOLA VEZ (sin API por tarjeta)
    # ═══════════════════════════════════════════════════════
    clientes_col_idx = resolver_col_indices_clientes(ws_clientes)

    mask_tecnico_asignado = df_reclamos['Tecnico_Limpio'].notna()

    # =====================================================
    # NOVEDADES
    # =====================================================
    if not df_novedades.empty:
        ultima = df_novedades.iloc[-1]
        fecha_nov = str(ultima.get('Fecha', ''))
        mensaje_nov = str(ultima.get('Mensaje', ''))
        if mensaje_nov and mensaje_nov != 'nan':
            st.info(f"📢 **({fecha_nov}):** {mensaje_nov}")

    # =====================================================
    # VISTA ADMIN
    # =====================================================
    if es_admin:
        st.markdown("### 👑 Panel de Administración")
        
        # --- PESTAÑAS ---
        tab_reclamos, tab_cajas = st.tabs(["📋 Gestión de Reclamos", "📦 Gestión de Cajas NAP"])

        with tab_reclamos:
            mask_en_curso = df_reclamos['Estado_Limpio'] == "En curso"
            mask_verificados = df_reclamos['Estado_Limpio'] == "Verificado"
            mask_pendientes = df_reclamos['Estado_Limpio'] == "Pendiente"
            mask_criticos = (df_reclamos['Horas_Transcurridas'] >= 48) & (df_reclamos['Estado_Limpio'].isin(["En curso", "Pendiente"]))

            count_curso = int(mask_en_curso.sum())
            count_verif = int(mask_verificados.sum())
            count_pend = int(mask_pendientes.sum())
            count_crit = int(mask_criticos.sum())

            col_s1, col_s2, col_s3, col_s4 = st.columns(4)
            with col_s1: st.metric("🟢 En Curso", count_curso)
            with col_s2: st.metric("✅ Verificados", count_verif)
            with col_s3: st.metric("⏸️ Pendientes", count_pend)
            with col_s4: st.metric("🔴 +48 hs", count_crit)

            # --- HERRAMIENTAS ADMIN ---
            with st.container(border=True):
                st.markdown("**⚙️ Herramientas de Gestión**")
                col_p1, col_p2, col_p3 = st.columns(3)

                with col_p1:
                    if st.button("📄 PDF Resumen", use_container_width=True):
                        with st.spinner("Generando PDF..."):
                            try:
                                estados_pdf = ["En curso", "Verificado"]
                                mask_pdf = df_reclamos['Estado_Limpio'].isin(estados_pdf)
                                df_activos_pdf = df_reclamos[mask_pdf & mask_tecnico_asignado].copy()
                                pdf_bytes = generar_pdf(df_activos_pdf, datetime.now().strftime("%d/%m/%Y"))
                                st.download_button(
                                    label="⬇️ Descargar PDF Resumen",
                                    data=pdf_bytes,
                                    file_name=f"Reclamos_{datetime.now().strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    use_container_width=True
                                )
                            except Exception as e:
                                st.error(f"Error al generar PDF: {e}")

                with col_p2:
                    st.markdown("🔒 Verificados → Resuelto")
                    confirmar_cierre = st.checkbox("Confirmar cierre", key="chk_cierre")
                    if st.button("🔒 Cierre Masivo", disabled=not confirmar_cierre, use_container_width=True):
                        try:
                            idxs = df_reclamos[mask_verificados].index.tolist()
                            if not idxs:
                                st.warning("No hay reclamos 'Verificado' para cerrar.")
                            else:
                                col_idx = df_reclamos.columns.get_loc('Estado') + 1
                                updates = []
                                for i in idxs:
                                    sheet_row_num = i + 2
                                    cell_range = gspread.utils.rowcol_to_a1(sheet_row_num, col_idx)
                                    updates.append({"range": cell_range, "values": [["Resuelto"]]})
                                safe_batch_update(ws_reclamos, updates)
                                st.cache_data.clear()
                                st.success(f"¡{len(updates)} reclamos cerrados como Resuelto!")
                                time.sleep(2)
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error en cierre masivo: {e}")

                with col_p3:
                    st.markdown("⏸️ En Curso → Pendiente")
                    confirmar_pendiente = st.checkbox("Confirmar pase", key="chk_pendiente")
                    if st.button("⏸️ Pasar a Pendiente", disabled=not confirmar_pendiente, use_container_width=True):
                        try:
                            idxs = df_reclamos[mask_en_curso].index.tolist()
                            if not idxs:
                                st.warning("No hay reclamos 'En curso' para pasar.")
                            else:
                                col_idx = df_reclamos.columns.get_loc('Estado') + 1
                                updates = []
                                for i in idxs:
                                    sheet_row_num = i + 2
                                    cell_range = gspread.utils.rowcol_to_a1(sheet_row_num, col_idx)
                                    updates.append({"range": cell_range, "values": [["Pendiente"]]})
                                safe_batch_update(ws_reclamos, updates)
                                st.cache_data.clear()
                                st.success(f"¡{len(updates)} reclamos pasados a Pendiente!")
                                time.sleep(2)
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error al pasar a Pendiente: {e}")

            # --- PDF VERIFICADOS DETALLADO ---
            with st.container(border=True):
                st.markdown("**📋 Exportación Detallada**")
                col_d1, col_d2 = st.columns(2)

                with col_d1:
                    if st.button("✅ PDF Verificados Detallado", use_container_width=True, type="primary"):
                        with st.spinner("Generando PDF detallado..."):
                            try:
                                df_verif_pdf = df_reclamos[mask_verificados].copy()
                                if df_verif_pdf.empty:
                                    st.warning("No hay reclamos verificados para exportar.")
                                else:
                                    df_verif_pdf = df_verif_pdf.sort_values(
                                        by=['Tecnico_Limpio', 'Nº Cliente'],
                                        ascending=[True, True]
                                    )
                                    pdf_bytes = generar_pdf_verificados_detallado(df_verif_pdf)
                                    st.download_button(
                                        label="⬇️ Descargar PDF Verificados",
                                        data=pdf_bytes,
                                        file_name=f"Verificados_Detallado_{datetime.now().strftime('%Y%m%d')}.pdf",
                                        mime="application/pdf",
                                        use_container_width=True
                                    )
                            except Exception as e:
                                st.error(f"Error al generar PDF: {e}")

                with col_d2:
                    st.caption("""
                    **Este PDF incluye:**
                    - Solo reclamos con estado **Verificado**
                    - Formato de tabla lineal (A4 vertical)
                    - Columnas: Nº Cliente, Nombre, Tipo, Precinto, Técnico
                    - Ordenado por técnico
                    """)

            # --- NOVEDADES ADMIN ---
            with st.container(border=True):
                st.markdown("**📢 Novedades del Día**")

                if not df_novedades.empty:
                    ultimas = df_novedades.tail(3).iloc[::-1]
                    for _, nrow in ultimas.iterrows():
                        f_nov = str(nrow.get('Fecha', ''))
                        m_nov = str(nrow.get('Mensaje', ''))
                        if m_nov and m_nov != 'nan':
                            st.markdown(f"📌 **{f_nov}:** {m_nov}")

                with st.form("form_novedad"):
                    nueva_novedad = st.text_input(
                        "Escribir nueva novedad",
                        placeholder="Ej: Hoy se trabaja hasta las 18",
                        key="nueva_nov_input"
                    )
                    submit_nov = st.form_submit_button("📢 Publicar Novedad", use_container_width=True)
                    if submit_nov:
                        if not nueva_novedad.strip():
                            st.error("❌ Escribí un mensaje.")
                        else:
                            try:
                                tz_arg = timezone(timedelta(hours=-3))
                                ahora = datetime.now(tz_arg)
                                fecha_str = f"{ahora.day}/{ahora.month}/{ahora.year}"
                                safe_append_row(ws_novedades, [fecha_str, nueva_novedad.strip()])
                                st.cache_data.clear()
                                st.success("✅ Novedad publicada.")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {e}")

            st.divider()

            # =====================================================
            # MENSAJE WHATSAPP
            # =====================================================
            if "mensaje_para_copiar" in st.session_state and st.session_state["mensaje_para_copiar"]:
                with st.expander("📱 Mensaje para WhatsApp (Click para abrir)", expanded=True):
                    st.info("📋 Copiá el siguiente texto y enviáselo al técnico:")
                    st.text_area(
                        "Texto del mensaje",
                        value=st.session_state["mensaje_para_copiar"],
                        height=250,
                        key="msg_display"
                    )
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        if st.button("✅ Ya lo envié (Limpiar)", use_container_width=True):
                            del st.session_state["mensaje_para_copiar"]
                            st.rerun()
                    with col_c2:
                        st.markdown("<small><i>Tip: Selecciona el texto → Ctrl+C</i></small>", unsafe_allow_html=True)
                st.divider()

            # --- CONTADORES POR TÉCNICO ---
            mask_verificados_tec = (df_reclamos['Estado_Limpio'] == "Verificado") & mask_tecnico_asignado
            verificados_por_tecnico = df_reclamos[mask_verificados_tec].groupby('Tecnico_Limpio').size().to_dict()

            # =====================================================
            # 🔍 BUSCADOR + FILTRO DE TÉCNICO
            # =====================================================
            mask_estado_display = df_reclamos['Estado_Limpio'] == "En curso"
            df_activos_display = df_reclamos[mask_estado_display & mask_tecnico_asignado].copy()

            if not df_activos_display.empty:
                search_query = st.text_input(
                    "🔍 Buscar reclamo en curso",
                    placeholder="Nº cliente, nombre, dirección, sector, técnico...",
                    key="search_reclamos_admin"
                )

                df_activos_display = filtrar_por_busqueda(df_activos_display, search_query)

                tecnicos_unicos = sorted(df_activos_display['Tecnico_Limpio'].dropna().unique()) if not df_activos_display.empty else []
                tecnico_seleccionado = st.selectbox("Filtrar por Técnico", ["Todos"] + tecnicos_unicos, index=0)

                if tecnico_seleccionado == "Todos":
                    df_filtrado = df_activos_display.copy()
                else:
                    df_filtrado = df_activos_display[df_activos_display['Tecnico_Limpio'] == tecnico_seleccionado].copy()

                df_filtrado = df_filtrado.sort_values(by='Horas_Transcurridas', ascending=False)

                if tecnico_seleccionado == "Todos":
                    tecnicos_en_vista = sorted(df_filtrado['Tecnico_Limpio'].dropna().unique())
                    total_en_curso = len(df_filtrado)
                    total_verificados = sum(verificados_por_tecnico.get(t, 0) for t in tecnicos_en_vista)
                    total_general = total_en_curso + total_verificados
                    st.markdown(f"**Total: {total_general}** (En Curso {total_en_curso} + Verificados {total_verificados})")

                    if search_query.strip():
                        st.caption(f"Mostrando {len(df_filtrado)} resultado(s) para \"{search_query.strip()}\"")

                    for tecnico, grupo in df_filtrado.groupby('Tecnico_Limpio'):
                        en_curso = len(grupo)
                        verificados = verificados_por_tecnico.get(tecnico, 0)
                        total = en_curso + verificados
                        with st.expander(f"👷 {tecnico} — {total} (Curso {en_curso} + OK {verificados})"):
                            for idx, row in grupo.iterrows():
                                renderizar_tarjeta(
                                    row, df_reclamos, ws_reclamos,
                                    es_admin=True, ws_clientes=ws_clientes,
                                    df_clientes_raw=df_clientes_raw,
                                    clientes_col_idx=clientes_col_idx,
                                    modo="en_curso",
                                    ws_cajas=ws_cajas, df_cajas_raw=df_cajas_raw
                                )
                else:
                    en_curso = len(df_filtrado)
                    verificados = verificados_por_tecnico.get(tecnico_seleccionado, 0)
                    total = en_curso + verificados
                    st.markdown(f"**{tecnico_seleccionado}: {total}** (Curso {en_curso} + OK {verificados})")

                    if search_query.strip():
                        st.caption(f"Mostrando {len(df_filtrado)} resultado(s) para \"{search_query.strip()}\"")

                    for idx, row in df_filtrado.iterrows():
                        renderizar_tarjeta(
                            row, df_reclamos, ws_reclamos,
                            es_admin=True, ws_clientes=ws_clientes,
                            df_clientes_raw=df_clientes_raw,
                            clientes_col_idx=clientes_col_idx,
                            modo="en_curso",
                            ws_cajas=ws_cajas, df_cajas_raw=df_cajas_raw
                        )
            else:
                st.info("ℹ️ No hay reclamos En curso con técnico asignado.")

            # =====================================================
            # SECCIÓN PENDIENTES
            # =====================================================
            st.divider()
            df_pendientes = df_reclamos[df_reclamos['Estado_Limpio'] == "Pendiente"].copy()

            if not df_pendientes.empty:
                df_pendientes = df_pendientes.sort_values(by='Horas_Transcurridas', ascending=False)

                with st.expander(f"📋 Reclamos Pendientes ({len(df_pendientes)})"):
                    search_pend = st.text_input(
                        "🔍 Buscar pendiente",
                        placeholder="Nº cliente, nombre, dirección...",
                        key="search_pendientes"
                    )
                    df_pendientes_filtrado = filtrar_por_busqueda(df_pendientes, search_pend)

                    for idx, row in df_pendientes_filtrado.iterrows():
                        renderizar_tarjeta(
                            row, df_reclamos, ws_reclamos,
                            es_admin=True, ws_clientes=ws_clientes,
                            df_clientes_raw=df_clientes_raw,
                            clientes_col_idx=clientes_col_idx,
                            modo="pendiente",
                            ws_cajas=ws_cajas, df_cajas_raw=df_cajas_raw
                        )
            else:
                st.success("🎉 No hay reclamos Pendientes.")

            # =====================================================
            # SECCIÓN VERIFICADOS (lista compacta)
            # =====================================================
            st.divider()
            df_verificados_lista = df_reclamos[df_reclamos['Estado_Limpio'] == "Verificado"].copy()

            if not df_verificados_lista.empty:
                with st.expander(f"✅ Verificados - Control ({len(df_verificados_lista)})"):
                    cols_disponibles = []
                    if 'Nº Cliente' in df_verificados_lista.columns:
                        cols_disponibles.append('Nº Cliente')
                    if 'Nombre' in df_verificados_lista.columns:
                        cols_disponibles.append('Nombre')
                    if 'precinto_cliente' in df_verificados_lista.columns:
                        cols_disponibles.append('precinto_cliente')
                    cols_disponibles.append('Tecnico_Limpio')

                    df_verif_compact = df_verificados_lista[cols_disponibles].copy()
                    df_verif_compact.rename(columns={
                        'Tecnico_Limpio': 'Técnico',
                        'precinto_cliente': 'Precinto'
                    }, inplace=True)
                    df_verif_compact['Precinto'] = df_verif_compact['Precinto'].fillna('Sin precinto')
                    df_verif_compact['Técnico'] = df_verif_compact['Técnico'].fillna('Sin asignar')

                    st.dataframe(df_verif_compact, use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ No hay reclamos verificados aún.")

        # =====================================================
        # PESTAÑA CAJAS NAP
        # =====================================================
        with tab_cajas:
            st.subheader("📦 Editor de Cajas NAP")

            if df_cajas_raw is not None and ws_cajas is not None:
                df_cajas_norm = df_cajas_raw.copy()
                df_cajas_norm["N De Caja"] = df_cajas_norm["N De Caja"].astype(str).str.strip()

                nro_caja = st.text_input(
                    "Ingresá el N° de Caja NAP",
                    placeholder="Ej: NAP-001",
                    key="search_nro_caja"
                ).strip()

                if nro_caja:
                    caja_data = df_cajas_norm[df_cajas_norm["N De Caja"] == nro_caja]

                    if caja_data.empty:
                        # ==========================================
                        # LA CAJA NO EXISTE - CREACION
                        # ==========================================
                        st.info("ℹ Esta caja NAP no existe en la base. Completá los datos para crearla.")

                        with st.form("form_crear_caja"):
                            col_c1, col_c2 = st.columns(2)

                            with col_c1:
                                nuevo_sector_caja = st.selectbox(
                                    "🔢 Sector*", options=SECTORES_DISPONIBLES, index=0, key="caja_sector_new"
                                )
                                nuevo_barrio = st.text_input("🏘️ Barrio*", placeholder="Nombre del barrio")

                            with col_c2:
                                nuevo_lat_caja = st.text_input("📍 Latitud", value="-26.", key="caja_lat_new")
                                nuevo_lon_caja = st.text_input("📍 Longitud", value="-59.", key="caja_lon_new")

                            col_c3, col_c4 = st.columns(2)
                            with col_c3:
                                nuevo_obs_caja = st.text_input("📝 Observación", placeholder="Observaciones (opcional)")
                                nueva_marca = st.selectbox("🏷️ Marca Equipo", options=MARCAS_EQUIPO, index=0, key="caja_marca_new")
                            with col_c4:
                                nuevo_splitter = st.selectbox(
                                    "🔀 Splitter*",
                                    options=SPLITTERS_DISPONIBLES,
                                    index=1,
                                    key="caja_splitter_new"
                                )

                            submit_crear_caja = st.form_submit_button("✅ Crear Nueva Caja NAP", use_container_width=True)

                            if submit_crear_caja:
                                if not nuevo_barrio.strip():
                                    st.error("⚠️ El Barrio es un campo obligatorio.")
                                else:
                                    try:
                                        float(nuevo_lat_caja.strip().replace(',', '.'))
                                        float(nuevo_lon_caja.strip().replace(',', '.'))

                                        fila_caja = [
                                            nro_caja,
                                            nuevo_sector_caja,
                                            nuevo_barrio.upper().strip(),
                                            nuevo_lat_caja.strip(),
                                            nuevo_lon_caja.strip(),
                                            nuevo_obs_caja.strip(),
                                            nueva_marca.strip(),
                                            nuevo_splitter.strip()
                                        ]

                                        success, error = _do_append(ws_cajas, fila_caja)

                                        if success:
                                            st.cache_data.clear()
                                            st.success(f"✅ Caja NAP `{nro_caja}` creada correctamente. Podés buscarla ahora para cargar los puertos.")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(f"❌ Error al crear la caja NAP: {error}")

                                    except ValueError:
                                        st.error("❌ Las coordenadas deben ser valores numéricos (ej: -26.123456).")
                                    except Exception as e:
                                        st.error(f"❌ Error inesperado: {str(e)}")

                    else:
                        # ==========================================
                        # LA CAJA SI EXISTE - EDICION
                        # ==========================================
                        caja = caja_data.iloc[0]
                        caja_row_idx = caja.name + 2

                        col_cr1, col_cr2, col_cr3, col_cr4, col_cr5 = st.columns(5)
                        with col_cr1:
                            st.markdown(f"**🔢 Sector:** {caja.get('Sector', 'N/A')}")
                        with col_cr2:
                            st.markdown(f"**🏘️ Barrio:** {caja.get('Barrio', 'N/A')}")
                        with col_cr3:
                            st.markdown(f"**🏷️ Marca Equipo:** {caja.get('Marca Equipo', 'N/A')}")
                        with col_cr4:
                            splitter_val = caja.get('Splitter', '')
                            splitter_display = splitter_val if splitter_val and str(splitter_val).strip() not in ('', 'nan', 'None') else 'Sin asignar'
                            st.markdown(f"**🔀 Splitter:** `{splitter_display}`")
                        with col_cr5:
                            lat_c = str(caja.get('Latitud', '')).strip()
                            lon_c = str(caja.get('Longitud', '')).strip()
                            if lat_c not in ("", "nan", "None") and lon_c not in ("", "nan", "None"):
                                try:
                                    float(lat_c.replace(',', '.'))
                                    float(lon_c.replace(',', '.'))
                                    maps_url_caja = f"https://www.google.com/maps?q={lat_c},{lon_c}"
                                    st.markdown(f"**🗺️** [Ver en Maps]({maps_url_caja})")
                                except (ValueError, TypeError):
                                    st.markdown("**🗺️** Geo. inválida")
                            else:
                                st.markdown("**🗺️** Sin georef.")

                        st.markdown("---")

                        # ACORDEON CAJA 1: EDITAR DATOS PRINCIPALES
                        with st.expander("✏️ Editar Datos de la Caja NAP (Sector, Barrio, Observación, Marca, Splitter)"):
                            with st.form(f"form_editar_caja_{caja_row_idx}"):
                                edit_ccol1, edit_ccol2 = st.columns(2)

                                with edit_ccol1:
                                    sector_actual_caja = str(caja.get("Sector", "1")).strip()
                                    try:
                                        sector_idx_caja = SECTORES_DISPONIBLES.index(sector_actual_caja) if sector_actual_caja in SECTORES_DISPONIBLES else 0
                                    except ValueError:
                                        sector_idx_caja = 0
                                    edit_sector_caja = st.selectbox(
                                        "🔢 Sector", options=SECTORES_DISPONIBLES, index=sector_idx_caja, key=f"caja_sec_{caja_row_idx}"
                                    )
                                    edit_barrio = st.text_input(
                                        "🏘️ Barrio", value=str(caja.get("Barrio", "")), key=f"caja_barrio_{caja_row_idx}"
                                    )
                                    edit_obs_caja = st.text_input(
                                        "📝 Observación", value=str(caja.get("Observacion", "")), key=f"caja_obs_{caja_row_idx}"
                                    )

                                with edit_ccol2:
                                    marca_actual = str(caja.get("Marca Equipo", "Huawei")).strip()
                                    try:
                                        marca_idx = MARCAS_EQUIPO.index(marca_actual) if marca_actual in MARCAS_EQUIPO else 0
                                    except ValueError:
                                        marca_idx = 0
                                    edit_marca = st.selectbox(
                                        "🏷️ Marca Equipo", options=MARCAS_EQUIPO, index=marca_idx, key=f"caja_marca_{caja_row_idx}"
                                    )

                                    splitter_actual = str(caja.get("Splitter", "")).strip()
                                    try:
                                        splitter_idx = SPLITTERS_DISPONIBLES.index(splitter_actual) if splitter_actual in SPLITTERS_DISPONIBLES else 1
                                    except ValueError:
                                        splitter_idx = 1
                                    edit_splitter = st.selectbox(
                                        "🔀 Splitter",
                                        options=SPLITTERS_DISPONIBLES,
                                        index=splitter_idx,
                                        key=f"caja_splitter_{caja_row_idx}"
                                    )

                                submit_edit_caja = st.form_submit_button("💾 Guardar Cambios en Caja NAP", use_container_width=True)

                                if submit_edit_caja:
                                    updates = []

                                    if str(caja.get("Sector", "")).strip() != edit_sector_caja:
                                        updates.append({"range": f"B{caja_row_idx}", "values": [[edit_sector_caja]]})

                                    if str(caja.get("Barrio", "")).strip() != edit_barrio.upper().strip():
                                        updates.append({"range": f"C{caja_row_idx}", "values": [[edit_barrio.upper().strip()]]})

                                    if str(caja.get("Observacion", "")).strip() != edit_obs_caja.strip():
                                        updates.append({"range": f"F{caja_row_idx}", "values": [[edit_obs_caja.strip()]]})

                                    if str(caja.get("Marca Equipo", "")).strip() != edit_marca.strip():
                                        updates.append({"range": f"G{caja_row_idx}", "values": [[edit_marca.strip()]]})

                                    if str(caja.get("Splitter", "")).strip() != edit_splitter.strip():
                                        updates.append({"range": f"H{caja_row_idx}", "values": [[edit_splitter.strip()]]})

                                    if updates:
                                        success, error = _do_batch_update(ws_cajas, updates)
                                        if success:
                                            st.cache_data.clear()
                                            st.success("✅ Datos de la caja NAP actualizados correctamente.")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(f"❌ Error al actualizar datos: {error}")
                                    else:
                                        st.info("ℹ️ No se detectaron cambios en los datos de la caja NAP.")

                        # ACORDEON CAJA 2: GEOREFERENCIA
                        with st.expander("🗺 Georreferencia de Caja NAP"):
                            lat_caja = str(caja.get("Latitud", "")).strip()
                            lon_caja = str(caja.get("Longitud", "")).strip()

                            has_geo_caja = False
                            if lat_caja not in ("", "nan", "None") and lon_caja not in ("", "nan", "None"):
                                try:
                                    float(lat_caja.replace(',', '.'))
                                    float(lon_caja.replace(',', '.'))
                                    has_geo_caja = True
                                except (ValueError, TypeError):
                                    has_geo_caja = False

                            if has_geo_caja:
                                st.success("✅ Georreferencia registrada")
                                maps_url_caja = f"https://www.google.com/maps?q={lat_caja},{lon_caja}"
                                st.markdown(f"🗺️ [Ver ubicación en Google Maps]({maps_url_caja})")

                                with st.form(f"form_editar_geo_caja_{caja_row_idx}"):
                                    edit_lat_caja = st.text_input("Latitud", value=lat_caja, key=f"caja_lat_edit_{caja_row_idx}")
                                    edit_lon_caja = st.text_input("Longitud", value=lon_caja, key=f"caja_lon_edit_{caja_row_idx}")
                                    submit_edit_geo_caja = st.form_submit_button("💾 Actualizar Coordenadas")

                                    if submit_edit_geo_caja:
                                        try:
                                            float(edit_lat_caja.strip().replace(',', '.'))
                                            float(edit_lon_caja.strip().replace(',', '.'))

                                            updates = [
                                                {"range": f"D{caja_row_idx}", "values": [[edit_lat_caja.strip()]]},
                                                {"range": f"E{caja_row_idx}", "values": [[edit_lon_caja.strip()]]}
                                            ]
                                            success, error = _do_batch_update(ws_cajas, updates)
                                            if success:
                                                st.cache_data.clear()
                                                st.success("✅ Coordenadas de caja NAP actualizadas.")
                                                time.sleep(1)
                                                st.rerun()
                                            else:
                                                st.error(f"❌ Error: {error}")
                                        except ValueError:
                                            st.error("❌ Las coordenadas deben ser valores numéricos.")
                            else:
                                st.info("ℹ️ Esta caja NAP no tiene georreferencia cargada. Ingresá las coordenadas:")
                                default_lat_caja = "-26."
                                default_lon_caja = "-59."

                                with st.form(f"form_cargar_geo_caja_{caja_row_idx}"):
                                    val_lat_caja = lat_caja if lat_caja not in ("nan", "None", "") else default_lat_caja
                                    val_lon_caja = lon_caja if lon_caja not in ("nan", "None", "") else default_lon_caja

                                    new_lat_caja = st.text_input("Latitud", value=val_lat_caja, key=f"caja_lat_new_{caja_row_idx}")
                                    new_lon_caja = st.text_input("Longitud", value=val_lon_caja, key=f"caja_lon_new_{caja_row_idx}")
                                    submitted_caja_geo = st.form_submit_button("💾 Guardar Coordenadas")

                                    if submitted_caja_geo:
                                        if not new_lat_caja.strip() or not new_lon_caja.strip():
                                            st.error("❌ Debés completar ambos campos para guardar.")
                                        else:
                                            try:
                                                float(new_lat_caja.strip().replace(',', '.'))
                                                float(new_lon_caja.strip().replace(',', '.'))

                                                updates = [
                                                    {"range": f"D{caja_row_idx}", "values": [[new_lat_caja.strip()]]},
                                                    {"range": f"E{caja_row_idx}", "values": [[new_lon_caja.strip()]]}
                                                ]
                                                success, error = _do_batch_update(ws_cajas, updates)
                                                if success:
                                                    st.cache_data.clear()
                                                    st.success("✅ Georreferencia de caja NAP guardada correctamente.")
                                                    time.sleep(1)
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ Error al guardar en la hoja: {error}")
                                            except ValueError:
                                                st.error("❌ Las coordenadas deben ser valores numéricos (ej: -26.123456).")

                        # ACORDEON CAJA 3: GESTION DE PUERTOS (PRECINTOS) - (DIVIDIDO EN 2 COLUMNAS)
                        with st.expander("🔌 Gestión de Puertos (Precintos)"):
                            splitter_actual = str(caja.get('Splitter', '1/4')).strip()
                            num_puertos = 4
                            if splitter_actual == "1/8":
                                num_puertos = 8
                            elif splitter_actual == "1/16":
                                num_puertos = 16

                            letras_columnas = ["I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X"]

                            with st.form(f"form_puertos_caja_{caja_row_idx}"):
                                st.markdown(f"**Splitter {splitter_actual}** — Se han habilitado **{num_puertos}** puertos.")
                                
                                inputs_puertos = []
                                mitad_puertos = num_puertos // 2
                                
                                col_p1, col_p2 = st.columns(2)
                                
                                # Generar dinámicamente los campos según el splitter en 2 columnas
                                for i in range(num_puertos):
                                    col_precinto = f"Precinto {i+1}"
                                    val_actual_puerto = str(caja.get(col_precinto, "")).strip()
                                    if val_actual_puerto in ("nan", "None"): val_actual_puerto = ""

                                    # Buscar a quién pertenece este precinto actualmente
                                    info_cliente = ""
                                    if val_actual_puerto:
                                        asociado = verificar_precinto_duplicado(df_clientes_raw, val_actual_puerto)
                                        if asociado is not None:
                                            info_cliente = f" (🟢 {asociado['Nº Cliente']} - {asociado['Nombre']})"
                                        else:
                                            info_cliente = " (🔴 Libre/Sin cliente)"
                                    
                                    # Decidir columna de destino
                                    target_col = col_p1 if i < mitad_puertos else col_p2
                                    
                                    with target_col:
                                        nuevo_val_puerto = st.text_input(
                                            f"Puerto {i+1}{info_cliente}", 
                                            value=val_actual_puerto, 
                                            key=f"puerto_{caja_row_idx}_{i}"
                                        )
                                        inputs_puertos.append(nuevo_val_puerto)

                                submit_puertos = st.form_submit_button("💾 Guardar Puertos y Asignar Caja a Clientes", use_container_width=True)

                                if submit_puertos:
                                    updates_caja = []
                                    updates_clientes = []

                                    for i in range(num_puertos):
                                        val_actual = str(caja.get(f"Precinto {i+1}", "")).strip()
                                        if val_actual in ("nan", "None"): val_actual = ""
                                        nuevo_val = inputs_puertos[i].strip()

                                        if val_actual != nuevo_val:
                                            letra = letras_columnas[i]
                                            updates_caja.append({"range": f"{letra}{caja_row_idx}", "values": [[nuevo_val]]})

                                        if nuevo_val:
                                            cli_asociado = verificar_precinto_duplicado(df_clientes_raw, nuevo_val)
                                            if cli_asociado is not None:
                                                cli_idx = cli_asociado.name + 2
                                                caja_actual_cli = str(cli_asociado.get("Caja NAP", "")).strip()
                                                if caja_actual_cli != nro_caja:
                                                    updates_clientes.append({"range": f"M{cli_idx}", "values": [[nro_caja]]})

                                    for i in range(num_puertos, 16):
                                        val_actual = str(caja.get(f"Precinto {i+1}", "")).strip()
                                        if val_actual and val_actual not in ("nan", "None"):
                                            letra = letras_columnas[i]
                                            updates_caja.append({"range": f"{letra}{caja_row_idx}", "values": [[""]]})

                                    exito = True
                                    
                                    if updates_caja:
                                        success_c, error_c = _do_batch_update(ws_cajas, updates_caja)
                                        if not success_c:
                                            st.error(f"❌ Error al guardar puertos de caja: {error_c}")
                                            exito = False
                                    
                                    if updates_clientes:
                                        success_cl, error_cl = _do_batch_update(ws_clientes, updates_clientes)
                                        if not success_cl:
                                            st.error(f"❌ Error al actualizar cajas en clientes: {error_cl}")
                                            exito = False
                                        else:
                                            st.success(f"✅ Se asignó automáticamente la Caja {nro_caja} a {len(updates_clientes)} cliente(s).")

                                    if exito and (updates_caja or updates_clientes):
                                        st.cache_data.clear()
                                        st.success("✅ Actualización completada correctamente.")
                                        time.sleep(1)
                                        st.rerun()
                                    elif not updates_caja and not updates_clientes:
                                        st.info("ℹ️ No se detectaron cambios en los puertos.")

    # =====================================================
    # VISTA TÉCNICO
    # =====================================================
    else:
        estados_tec = ["En curso"]
        mask_estado_tec = df_reclamos['Estado_Limpio'].isin(estados_tec)
        mask_tecnico = df_reclamos['Técnico'].str.contains(rol, case=False, na=False)
        mis_reclamos = df_reclamos[mask_tecnico & mask_estado_tec].copy()
        mis_reclamos = mis_reclamos.sort_values(by='Horas_Transcurridas', ascending=False)

        st.markdown(f"### 📋 Reclamos en curso: {len(mis_reclamos)}")

        if mis_reclamos.empty:
            st.success("🎉 No tenés reclamos pendientes.")
            return

        search_tec = st.text_input(
            "🔍 Buscar en mis reclamos",
            placeholder="Nº cliente, nombre, dirección...",
            key="search_tecnico"
        )
        mis_reclamos = filtrar_por_busqueda(mis_reclamos, search_tec)

        for idx, row in mis_reclamos.iterrows():
            renderizar_tarjeta(
                row, df_reclamos, ws_reclamos,
                es_admin=False, ws_clientes=ws_clientes,
                df_clientes_raw=df_clientes_raw,
                clientes_col_idx=clientes_col_idx,
                modo="en_curso",
                ws_cajas=ws_cajas, df_cajas_raw=df_cajas_raw
            )

# =========================================================
# FLUJO PRINCIPAL
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    saved_user = load_cookie("fusion_user")
    if saved_user:
        try:
            ws_reclamos, ws_clientes, ws_usuarios, ws_novedades, ws_cajas = init_google_sheets()
            df_usuarios = pd.DataFrame(safe_get_all_records(ws_usuarios))
            df_usuarios.columns = df_usuarios.columns.str.strip()

            user_row = df_usuarios[df_usuarios['username'] == saved_user]

            if not user_row.empty:
                rol = str(user_row.iloc[0]['rol']).strip()
                rol_lower = rol.lower()
                es_admin = rol_lower in ['admin', 'oficina', 'supervisor']

                st.session_state["authenticated"] = True
                st.session_state["user_name"] = user_row.iloc[0]['nombre']
                st.session_state["rol"] = rol
                st.session_state["es_admin"] = es_admin
                st.rerun()
        except:
            pass

    login_screen()
else:
    main_app()