import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
import time
from fpdf import FPDF
import io
import numpy as np

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
# INYECCIÓN PWA (manifest + meta tags)
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
# CONFIGURACIÓN GOOGLE SHEETS
# =========================================================
SHEET_ID = "13R_3Mdr25Jd-nGhK7CxdcbKkFWLc0LPdYrOLOY8sZJo"

WORKSHEET_RECLAMOS = "Reclamos"
WORKSHEET_CLIENTES = "Clientes"
WORKSHEET_USUARIOS = "usuarios"
WORKSHEET_NOVEDADES = "Novedades"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# =========================================================
# LISTA DE TÉCNICOS
# =========================================================
TECNICOS_DISPONIBLES = [
    "CONEJO", "JUAN", "JUNIOR", "MAXI", "MARKI",
    "RAMON", "RENE", "ROQUE", "VIKI", "OFICINA", "BASE"
]

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
        
        try:
            ws_novedades = spreadsheet.worksheet(WORKSHEET_NOVEDADES)
        except gspread.exceptions.WorksheetNotFound:
            ws_novedades = spreadsheet.add_worksheet(title=WORKSHEET_NOVEDADES, rows=10, cols=2)
            ws_novedades.update('A1:B1', [['Fecha', 'Mensaje']])
        
        return ws_reclamos, ws_clientes, ws_usuarios, ws_novedades
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        st.stop()

# =========================================================
# CARGA DE DATOS
# =========================================================
@st.cache_data(ttl=120)
def cargar_datos():
    ws_reclamos, ws_clientes, ws_usuarios, ws_novedades = init_google_sheets()
    df_reclamos = pd.DataFrame(ws_reclamos.get_all_records())
    df_clientes = pd.DataFrame(ws_clientes.get_all_records())
    df_usuarios = pd.DataFrame(ws_usuarios.get_all_records())
    
    # LIMPIEZA DE NOMBRES DE COLUMNAS: Evita errores por espacios accidentales en Google Sheets
    df_reclamos.columns = df_reclamos.columns.str.strip()
    df_clientes.columns = df_clientes.columns.str.strip()
    df_usuarios.columns = df_usuarios.columns.str.strip()

    try:
        df_novedades = pd.DataFrame(ws_novedades.get_all_records())
        df_novedades.columns = df_novedades.columns.str.strip()
    except:
        df_novedades = pd.DataFrame(columns=['Fecha', 'Mensaje'])

    df_clientes_raw = df_clientes.copy()

    df_c = df_clientes.rename(columns={
        'Nº Cliente': 'nro_cliente_cli', 
        'Latitud': 'lat', 
        'Longitud': 'lon',
        'N° de Precinto': 'precinto_cliente'
    })
    df_c['nro_cliente_cli'] = df_c['nro_cliente_cli'].astype(str)
    df_c['lat'] = pd.to_numeric(df_c['lat'].astype(str).str.replace(',', '.'), errors='coerce')
    df_c['lon'] = pd.to_numeric(df_c['lon'].astype(str).str.replace(',', '.'), errors='coerce')
    
    df_c['precinto_cliente'] = df_c['precinto_cliente'].replace(['*', '', ' '], np.nan)

    datos_cliente = df_c[['nro_cliente_cli', 'lat', 'lon', 'precinto_cliente']].drop_duplicates(subset=['nro_cliente_cli'])

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

    return df_r, df_usuarios, df_clientes_raw, df_novedades

# =========================================================
# FUNCIÓN PARA DIBUJAR TARJETAS
# =========================================================
def renderizar_tarjeta(row, df_reclamos, ws_reclamos, es_admin=False, ws_clientes=None, df_clientes_raw=None):
    sheet_row_num = row.name + 2 
    horas = row['Horas_Transcurridas']

    badge = "🟢 Normal"
    if pd.notna(horas):
        if horas >= 48: badge = "🔴 +48 hs"
        elif horas >= 24: badge = "🟡 +24 hs"

    direccion = str(row.get('Dirección', 'Sin dirección')) if pd.notna(row.get('Dirección')) else 'Sin dirección'
    telefono = str(row.get('Teléfono', 'Sin teléfono')) if pd.notna(row.get('Teléfono')) else 'Sin teléfono'
    tipo_reclamo = str(row.get('Tipo de reclamo', ''))
    detalles = str(row.get('Detalles', '')) if pd.notna(row.get('Detalles')) and str(row.get('Detalles')) != '*' else ''
    sector = str(row.get('Sector', '')) if pd.notna(row.get('Sector')) else ''
    nombre_cliente = str(row.get('Nombre', ''))
    nro_cliente = str(row.get('Nº Cliente', ''))
    
    precinto = ''
    if pd.notna(row.get('precinto_cliente')) and str(row.get('precinto_cliente')) not in ['nan', '*', '']:
        precinto = str(row.get('precinto_cliente'))

    if pd.notna(horas):
        if horas < 1: texto_tiempo = f"hace {int(horas * 60)} min"
        elif horas < 24: texto_tiempo = f"hace {int(horas)} hs"
        else: texto_tiempo = f"hace {int(horas / 24)} días"
    else: texto_tiempo = "Fecha inválida"

    cliente_fila = None
    if ws_clientes is not None and df_clientes_raw is not None:
        df_cl = df_clientes_raw.copy()
        df_cl['Nº Cliente'] = df_cl['Nº Cliente'].astype(str).str.strip()
        cliente_match = df_cl[df_cl['Nº Cliente'] == nro_cliente]
        if not cliente_match.empty:
            cliente_fila = cliente_match.index[0] + 2

    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1: st.markdown(f"### 🎫 Nº {row['Nº Cliente']} - {nombre_cliente}")
        with col2: st.markdown(f"**{badge}**")

        st.caption(texto_tiempo)
        st.markdown(f"📍 **Sector:** {sector}")
        st.markdown(f"**Dirección:** {direccion}")
        st.markdown(f"📞 **Teléfono:** {telefono}")
        st.markdown(f"⚙️ **Reclamo:** {tipo_reclamo}")

        if detalles: st.info(f"📝 Detalles: {detalles}")

        if precinto: 
            st.markdown(f"🔒 **Precinto:** {precinto}")
        else:
            st.caption("🔒 Precinto: No registrado")

        tiene_ubicacion = pd.notna(row.get('lat')) and pd.notna(row.get('lon'))
        if tiene_ubicacion:
            maps_url = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}"
            st.link_button("📍 Abrir ubicación en Google Maps", maps_url, use_container_width=True)
        else:
            st.caption("📍 Sin ubicación registrada")

        if es_admin and cliente_fila is not None:
            if not precinto or not tiene_ubicacion:
                st.markdown("---")
                st.markdown("**✏️ Completar datos del cliente**")
                
                if not precinto:
                    with st.form(f"form_precinto_{nro_cliente}_{sheet_row_num}"):
                        new_precinto = st.text_input("N° de Precinto", key=f"pint_{nro_cliente}_{sheet_row_num}")
                        submit_p = st.form_submit_button("💾 Guardar Precinto")
                        if submit_p:
                            if not new_precinto.strip():
                                st.error("❌ Ingresá un número de precinto.")
                            else:
                                try:
                                    cell = gspread.utils.rowcol_to_a1(cliente_fila, 6)
                                    ws_clientes.batch_update([{"range": cell, "values": [[new_precinto.strip()]]}])
                                    st.cache_data.clear()
                                    st.success("✅ Precinto guardado.")
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error: {e}")
                
                if not tiene_ubicacion:
                    with st.form(f"form_geo_{nro_cliente}_{sheet_row_num}"):
                        lat_raw = str(cliente_match.iloc[0].get('Latitud', '')).strip()
                        lon_raw = str(cliente_match.iloc[0].get('Longitud', '')).strip()
                        val_lat = lat_raw if lat_raw not in ("nan", "None", "") else "-26."
                        val_lon = lon_raw if lon_raw not in ("nan", "None", "") else "-59."
                        
                        new_lat = st.text_input("Latitud", value=val_lat, key=f"lt_{nro_cliente}_{sheet_row_num}")
                        new_lon = st.text_input("Longitud", value=val_lon, key=f"ln_{nro_cliente}_{sheet_row_num}")
                        submit_g = st.form_submit_button("💾 Guardar Coordenadas")
                        if submit_g:
                            if not new_lat.strip() or not new_lon.strip():
                                st.error("❌ Completá ambos campos.")
                            else:
                                try:
                                    float(new_lat.strip().replace(',', '.'))
                                    float(new_lon.strip().replace(',', '.'))
                                    updates = [
                                        {"range": gspread.utils.rowcol_to_a1(cliente_fila, 10), "values": [[new_lat.strip()]]},
                                        {"range": gspread.utils.rowcol_to_a1(cliente_fila, 11), "values": [[new_lon.strip()]]}
                                    ]
                                    ws_clientes.batch_update(updates)
                                    st.cache_data.clear()
                                    st.success("✅ Coordenadas guardadas.")
                                    time.sleep(1)
                                    st.rerun()
                                except ValueError:
                                    st.error("❌ Las coordenadas deben ser numéricas (ej: -26.123456).")
                                except Exception as e:
                                    st.error(f"❌ Error: {e}")

        # OBSERVACIÓN + VERIFICAR
        st.markdown("---")
        with st.form(f"form_verify_{sheet_row_num}"):
            obs = st.text_input(
                "📝 Observación", 
                placeholder="Ej: Caja con mala señal",
                key=f"obs_{sheet_row_num}"
            )
            submit_verify = st.form_submit_button("✅ Verificar Trabajo", use_container_width=True)
            
            if submit_verify:
                try:
                    col_idx = df_reclamos.columns.get_loc('Estado') + 1
                    ws_reclamos.update_cell(sheet_row_num, col_idx, "Verificado")
                    
                    if obs.strip() and cliente_fila is not None:
                        tz_arg = timezone(timedelta(hours=-3))
                        ahora = datetime.now(tz_arg)
                        fecha_obs = f"{ahora.day}/{ahora.month}/{ahora.year}"
                        obs_text = f"{fecha_obs}: {obs.strip().upper()}"
                        
                        current_val = ws_clientes.cell(cliente_fila, 9).value or ""
                        if current_val and current_val.strip():
                            new_val = current_val.strip() + "\n" + obs_text
                        else:
                            new_val = obs_text
                        
                        ws_clientes.update_cell(cliente_fila, 9, new_val)
                    
                    st.cache_data.clear()
                    st.success("¡Reclamo verificado!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al actualizar: {e}")

# =========================================================
# GENERADOR DE PDF (Original - Resumen por Técnico)
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
# GENERADOR DE PDF VERIFICADOS DETALLADO (NUEVO - Lineal)
# =========================================================
class PDFVerificados(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 11)
        self.cell(0, 8, f'Trabajos Verificados - {datetime.now().strftime("%d/%m/%Y")}', 0, 1, 'C')
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()} / {self.alias_nb_pages()}', 0, 0, 'C')


def generar_pdf_verificados_detallado(df_verificados):
    """
    Genera un PDF lineal con tabla de verificados.
    Columnas: Nº Cliente | Nombre | Tipo de Reclamo | Precinto | Técnico
    """
    pdf = PDFVerificados('L', 'mm', 'A4')  # 'L' = Landscape (apaisado) para más espacio
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.alias_nb_pages()
    pdf.add_page()

    # === DEFINICIÓN DE COLUMNAS (ancho total A4 apaisado ~277mm) ===
    margin_x = 8
    usable_width = 277 - (margin_x * 2)  # 261mm disponibles

    col_cliente = 28       # Nº Cliente
    col_nombre = 65        # Nombre
    col_tipo = 80          # Tipo de reclamo
    col_precinto = 35      # Precinto
    col_tecnico = 53       # Técnico
    # Total: 261mm

    col_widths = [col_cliente, col_nombre, col_tipo, col_precinto, col_tecnico]
    col_headers = ['Nº Cliente', 'Nombre', 'Tipo de Reclamo', 'Precinto', 'Técnico']
    col_x_positions = [margin_x]
    for w in col_widths[:-1]:
        col_x_positions.append(col_x_positions[-1] + w)

    row_height = 6
    header_height = 8
    margin_y = 15

    # === CONTADOR TOTAL ===
    total_verificados = len(df_verificados)

    # === TÍTULO CON CONTADOR ===
    pdf.set_xy(margin_x, margin_y)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(usable_width, 6, f'Total de trabajos verificados: {total_verificados}', 0, 1, 'L', fill=True)
    pdf.ln(3)

    # === ENCABEZADO DE TABLA ===
    current_y = pdf.get_y()

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(60, 60, 60)
    pdf.set_text_color(255, 255, 255)  # Texto blanco

    for i, header in enumerate(col_headers):
        header_safe = header.encode('latin-1', 'replace').decode('latin-1')
        pdf.set_xy(col_x_positions[i], current_y)
        pdf.cell(col_widths[i], header_height, header_safe, 1, 0, 'C', fill=True)

    pdf.set_text_color(0, 0, 0)  # Volver a negro
    current_y += header_height

    # === FILAS DE DATOS ===
    pdf.set_font('Helvetica', '', 7.5)

    fila_num = 0
    for idx, row in df_verificados.iterrows():
        # Extraer y limpiar datos
        nro_cliente = str(row.get('Nº Cliente', '')).encode('latin-1', 'replace').decode('latin-1')
        nombre = str(row.get('Nombre', '')).encode('latin-1', 'replace').decode('latin-1')
        tipo_reclamo = str(row.get('Tipo de reclamo', '')).encode('latin-1', 'replace').decode('latin-1')
        
        # Precinto: puede ser NaN
        precinto_raw = row.get('precinto_cliente', '')
        if pd.notna(precinto_raw) and str(precinto_raw) not in ['nan', '*', '', ' ']:
            precinto = str(precinto_raw).encode('latin-1', 'replace').decode('latin-1')
        else:
            precinto = '-'
        
        # Técnico: puede ser NaN
        tecnico_raw = row.get('Tecnico_Limpio', '')
        if pd.notna(tecnico_raw) and str(tecnico_raw).strip() not in ['nan', '', ' ']:
            tecnico = str(tecnico_raw).encode('latin-1', 'replace').decode('latin-1')
        else:
            tecnico = 'Sin asignar'

        datos_fila = [nro_cliente, nombre, tipo_reclamo, precinto, tecnico]

        # Color de fondo alternado para facilitar lectura
        if fila_num % 2 == 0:
            pdf.set_fill_color(255, 255, 255)
        else:
            pdf.set_fill_color(245, 245, 245)

        # Dibujar cada celda con truncado si es necesario
        for i, dato in enumerate(datos_fila):
            ancho_disponible = col_widths[i] - 2  # -2mm de padding interno

            # Truncar si el texto es más ancho que la celda
            if pdf.get_string_width(dato) > ancho_disponible:
                while pdf.get_string_width(dato + "..") > ancho_disponible and len(dato) > 3:
                    dato = dato[:-1]
                dato = dato.rstrip(' .-') + ".."

            pdf.set_xy(col_x_positions[i] + 1, current_y)
            pdf.cell(col_widths[i] - 2, row_height, dato, 1, 0, 'L', fill=True)

        current_y += row_height
        fila_num += 1

    # === PIE DE TABLA ===
    pdf.ln(3)
    pdf.set_font('Helvetica', 'I', 7)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f'Documento generado el {datetime.now().strftime("%d/%m/%Y a las %H:%M")} - Fusion App Técnicos', 0, 1, 'C')

    return bytes(pdf.output())

# =========================================================
# GENERADOR DE MENSAJE WHATSAPP (Copia y Pega)
# =========================================================
def generar_mensaje_asignacion(row, tecnicos_asignados):
    """
    Genera un texto formateado con los datos del reclamo para enviar por WhatsApp.
    """
    
    cliente = str(row.get('Nombre', 'Sin Nombre'))
    nro_cliente = str(row.get('Nº Cliente', ''))
    direccion = str(row.get('Dirección', 'Sin dirección'))
    telefono = str(row.get('Teléfono', 'Sin teléfono'))
    tipo_reclamo = str(row.get('Tipo de reclamo', ''))
    detalles = str(row.get('Detalles', ''))
    sector = str(row.get('Sector', ''))
    
    if detalles == '*' or detalles == 'nan': detalles = ""
    
    precinto = ''
    if pd.notna(row.get('precinto_cliente')) and str(row.get('precinto_cliente')) not in ['nan', '*', '']:
        precinto = str(row.get('precinto_cliente'))
    
    linea_separadora = "------------------------------------------------"
    
    msg = f"🔧 *NUEVA ASIGNACIÓN DE TRABAJO* 🔧\n"
    msg += linea_separadora + "\n"
    msg += f"👷 *TÉCNICO(S):* {tecnicos_asignados}\n"
    msg += f"👤 *CLIENTE:* {cliente} (Nº {nro_cliente})\n"
    
    if sector: msg += f"📍 *SECTOR:* {sector}\n"
    
    msg += f"🏠 *DIRECCIÓN:* {direccion}\n"
    if telefono and telefono != 'Sin teléfono': 
        msg += f"📞 *TEL:* {telefono}\n"
        
    if precinto:
        msg += f"🔒 *PRECINTO:* {precinto}\n"
    else:
        msg += f"🔒 *PRECINTO:* No cuenta con número de precinto\n"
        
    msg += linea_separadora + "\n"
    msg += f"⚙️ *RECLAMO:* {tipo_reclamo}\n"
    if detalles: msg += f"📝 *DETALLE:* {detalles}\n"
    
    tiene_ubicacion = pd.notna(row.get('lat')) and pd.notna(row.get('lon'))
    if tiene_ubicacion:
        maps_link = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}"
        msg += linea_separadora + "\n"
        msg += f"🗺️ *UBICACIÓN:* {maps_link}\n"
        msg += "(Click en el link para abrir Google Maps)"
    else:
        msg += linea_separadora + "\n"
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
                ws_reclamos, ws_clientes, ws_usuarios, ws_novedades = init_google_sheets()
                df_usuarios = pd.DataFrame(ws_usuarios.get_all_records())
                
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

    # Header
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.markdown(f"### 👷 {st.session_state.user_name} ({'Admin' if es_admin else 'Técnico'})")
    with col2:
        if st.button("🔄"):
            st.cache_data.clear()
            st.rerun()
    with col3:
        if st.button("🚪 Salir"):
            delete_cookie("fusion_user")
            st.session_state.authenticated = False
            st.rerun()

    st.divider()

    # Datos
    df_reclamos, _, df_clientes_raw, df_novedades = cargar_datos()
    ws_reclamos, ws_clientes, _, ws_novedades = init_google_sheets()

    mask_tecnico_asignado = df_reclamos['Tecnico_Limpio'].notna()

    # =====================================================
    # NOVEDADES - Visible para TODOS
    # =====================================================
    if not df_novedades.empty:
        ultima = df_novedades.iloc[-1]
        fecha_nov = str(ultima.get('Fecha', ''))
        mensaje_nov = str(ultima.get('Mensaje', ''))
        if mensaje_nov and mensaje_nov != 'nan':
            st.info(f"📢 **Novedad ({fecha_nov}):** {mensaje_nov}")

    # =====================================================
    # VISTA ADMIN
    # =====================================================
    if es_admin:
        st.markdown("### 👑 Panel de Administración")
        
        # --- RESUMEN DEL DÍA ---
        mask_en_curso = df_reclamos['Estado_Limpio'] == "En curso"
        mask_verificados = df_reclamos['Estado_Limpio'] == "Verificado"
        mask_pendientes = df_reclamos['Estado_Limpio'] == "Pendiente"
        mask_criticos = (df_reclamos['Horas_Transcurridas'] >= 48) & (df_reclamos['Estado_Limpio'].isin(["En curso", "Pendiente"]))
        
        count_curso = int(mask_en_curso.sum())
        count_verif = int(mask_verificados.sum())
        count_pend = int(mask_pendientes.sum())
        count_crit = int(mask_criticos.sum())
        
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        with col_s1:
            st.metric("🟢 En Curso", count_curso)
        with col_s2:
            st.metric("✅ Verificados", count_verif)
        with col_s3:
            st.metric("⏸️ Pendientes", count_pend)
        with col_s4:
            st.metric("🔴 +48 hs", count_crit)
        
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
                            ws_reclamos.batch_update(updates)
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
                            ws_reclamos.batch_update(updates)
                            st.cache_data.clear()
                            st.success(f"¡{len(updates)} reclamos pasados a Pendiente!")
                            time.sleep(2)
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error al pasar a Pendiente: {e}")

        # --- BOTÓN NUEVO: PDF VERIFICADOS DETALLADO ---
        with st.container(border=True):
            st.markdown("**📋 Exportación Detallada**")
            col_d1, col_d2 = st.columns(2)
            
            with col_d1:
                if st.button("✅ PDF Verificados Detallado", use_container_width=True, type="primary"):
                    with st.spinner("Generando PDF detallado..."):
                        try:
                            # Filtrar SOLO verificados
                            df_verif_pdf = df_reclamos[mask_verificados].copy()
                            
                            if df_verif_pdf.empty:
                                st.warning("No hay reclamos verificados para exportar.")
                            else:
                                # Ordenar por técnico y luego por número de cliente
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
                - Formato de tabla lineal (apaisado)
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
                            ws_novedades.append_row([fecha_str, nueva_novedad.strip()])
                            st.cache_data.clear()
                            st.success("✅ Novedad publicada.")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {e}")
        
        st.divider()

        # =====================================================
        # VISUALIZADOR DE MENSAJE PARA WHATSAPP (Si existe)
        # =====================================================
        if "mensaje_para_copiar" in st.session_state and st.session_state["mensaje_para_copiar"]:
            with st.expander("📱 Mensaje generado para WhatsApp (Click para abrir)", expanded=True):
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
                    st.markdown("<small><i>Tip: Selecciona el texto -> Ctrl+C</i></small>", unsafe_allow_html=True)
            
            st.divider()

        # --- CONTADORES POR TÉCNICO ---
        mask_verificados_tec = (df_reclamos['Estado_Limpio'] == "Verificado") & mask_tecnico_asignado
        verificados_por_tecnico = df_reclamos[mask_verificados_tec].groupby('Tecnico_Limpio').size().to_dict()

        # --- LISTADO EN CURSO ---
        estados_display = ["En curso"]
        mask_estado_display = df_reclamos['Estado_Limpio'].isin(estados_display)
        df_activos_display = df_reclamos[mask_estado_display & mask_tecnico_asignado].copy()

        if not df_activos_display.empty:
            tecnicos_unicos = sorted(df_activos_display['Tecnico_Limpio'].unique())
            tecnico_seleccionado = st.selectbox("Filtrar por Técnico", ["Todos"] + tecnicos_unicos, index=0)
            
            if tecnico_seleccionado == "Todos":
                df_filtrado = df_activos_display.copy()
            else:
                df_filtrado = df_activos_display[df_activos_display['Tecnico_Limpio'] == tecnico_seleccionado].copy()

            df_filtrado = df_filtrado.sort_values(by='Horas_Transcurridas', ascending=False)

            if tecnico_seleccionado == "Todos":
                total_en_curso = len(df_filtrado)
                total_verificados = sum(verificados_por_tecnico.get(t, 0) for t in tecnicos_unicos)
                total_general = total_en_curso + total_verificados
                st.markdown(f"**Total: {total_general} (En Curso {total_en_curso} + Verificados {total_verificados})**")
                
                for tecnico, grupo in df_filtrado.groupby('Tecnico_Limpio'):
                    en_curso = len(grupo)
                    verificados = verificados_por_tecnico.get(tecnico, 0)
                    total = en_curso + verificados
                    with st.expander(f"👷 {tecnico} {total} (En Curso {en_curso} + Verificados {verificados})"):
                        for idx, row in grupo.iterrows():
                            renderizar_tarjeta(
                                row, df_reclamos, ws_reclamos, 
                                es_admin=True, ws_clientes=ws_clientes, df_clientes_raw=df_clientes_raw
                            )
            else:
                en_curso = len(df_filtrado)
                verificados = verificados_por_tecnico.get(tecnico_seleccionado, 0)
                total = en_curso + verificados
                st.markdown(f"**{tecnico_seleccionado}: {total} (En Curso {en_curso} + Verificados {verificados})**")
                
                for idx, row in df_filtrado.iterrows():
                    renderizar_tarjeta(
                        row, df_reclamos, ws_reclamos, 
                        es_admin=True, ws_clientes=ws_clientes, df_clientes_raw=df_clientes_raw
                    )
        else:
            st.info("ℹ️ No hay reclamos En curso con técnico asignado.")

        # SECCIÓN PENDIENTES
        mask_pend = df_reclamos['Estado_Limpio'] == "Pendiente"
        df_pendientes = df_reclamos[mask_pend].copy()

        st.divider()

        if not df_pendientes.empty:
            df_pendientes = df_pendientes.sort_values(by='Horas_Transcurridas', ascending=False)
            
            with st.expander(f"📋 Reclamos Pendientes ({len(df_pendientes)})"):
                for idx, row in df_pendientes.iterrows():
                    sheet_row_num = row.name + 2
                    nro_cliente = str(row.get('Nº Cliente', ''))
                    nombre_cliente = str(row.get('Nombre', ''))
                    tipo_reclamo = str(row.get('Tipo de reclamo', ''))
                    sector = str(row.get('Sector', '')) if pd.notna(row.get('Sector')) else ''
                    direccion = str(row.get('Dirección', 'Sin dirección')) if pd.notna(row.get('Dirección')) else 'Sin dirección'
                    telefono = str(row.get('Teléfono', 'Sin teléfono')) if pd.notna(row.get('Teléfono')) else 'Sin teléfono'
                    detalles_pen = str(row.get('Detalles', '')) if pd.notna(row.get('Detalles')) and str(row.get('Detalles')) != '*' else ''
                    horas_pen = row['Horas_Transcurridas']

                    badge_pen = ""
                    if pd.notna(horas_pen):
                        if horas_pen >= 48: badge_pen = "🔴 +48 hs"
                        elif horas_pen >= 24: badge_pen = "🟡 +24 hs"
                        else: badge_pen = "🟢 Normal"
                    
                    if pd.notna(horas_pen):
                        if horas_pen < 1: tiempo_pen = f"hace {int(horas_pen * 60)} min"
                        elif horas_pen < 24: tiempo_pen = f"hace {int(horas_pen)} hs"
                        else: tiempo_pen = f"hace {int(horas_pen / 24)} días"
                    else: tiempo_pen = "Fecha inválida"

                    tiene_ubicacion_pen = pd.notna(row.get('lat')) and pd.notna(row.get('lon'))

                    with st.container(border=True):
                        col_h1, col_h2 = st.columns([4, 1])
                        with col_h1:
                            st.markdown(f"**🎫 Nº {nro_cliente} - {nombre_cliente}**")
                        with col_h2:
                            if badge_pen: st.markdown(f"**{badge_pen}**")
                        
                        st.caption(f"⏸️ Pendiente · {tiempo_pen}")
                        st.markdown(f"📍 **Sector:** {sector}")
                        st.markdown(f"**Dirección:** {direccion}")
                        st.markdown(f"📞 **Teléfono:** {telefono}")
                        st.markdown(f"⚙️ **Reclamo:** {tipo_reclamo}")
                        
                        if detalles_pen: st.info(f"📝 Detalles: {detalles_pen}")
                        
                        if tiene_ubicacion_pen:
                            maps_url_pen = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}"
                            st.link_button("📍 Abrir ubicación en Google Maps", maps_url_pen, use_container_width=True)

                        with st.form(f"form_asignar_{nro_cliente}_{sheet_row_num}"):
                            tecnicos_sel = st.multiselect(
                                "👷 Asignar técnico(s)",
                                TECNICOS_DISPONIBLES,
                                key=f"ms_tec_{nro_cliente}_{sheet_row_num}"
                            )
                            submit_asignar = st.form_submit_button("🚀 Asignar y poner En Curso", use_container_width=True)
                            
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
                                        ws_reclamos.batch_update(updates)
                                        
                                        mensaje_whatsapp = generar_mensaje_asignacion(row, tecnicos_str)
                                        
                                        st.session_state["mensaje_para_copiar"] = mensaje_whatsapp
                                        
                                        st.cache_data.clear()
                                        st.success(f"✅ Asignado a **{tecnicos_str}** y puesto En Curso.")
                                        time.sleep(0.5)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"❌ Error al asignar: {e}")
        else:
            st.success("🎉 No hay reclamos Pendientes.")

        # =====================================================================
        # SECCIÓN VERIFICADOS (LISTA COMPACTA EXCLUSIVA ADMIN)
        # =====================================================================
        st.divider()
        df_verificados_lista = df_reclamos[df_reclamos['Estado_Limpio'] == "Verificado"].copy()

        if not df_verificados_lista.empty:
            with st.expander(f"✅ Reclamos Verificados - Control ({len(df_verificados_lista)})"):
                cols_disponibles = []
                if 'Nº Cliente' in df_verificados_lista.columns:
                    cols_disponibles.append('Nº Cliente')
                if 'Nombre' in df_verificados_lista.columns:
                    cols_disponibles.append('Nombre')
                
                if 'precinto_cliente' in df_verificados_lista.columns:
                    cols_disponibles.append('precinto_cliente')
                
                cols_disponibles.append('Tecnico_Limpio')
                
                df_verif_compact = df_verificados_lista[cols_disponibles].copy()
                
                nuevos_nombres = {
                    'Tecnico_Limpio': 'Técnico',
                    'precinto_cliente': 'Precinto'
                }
                df_verif_compact.rename(columns=nuevos_nombres, inplace=True)
                
                df_verif_compact['Precinto'] = df_verif_compact['Precinto'].fillna('Sin precinto')
                df_verif_compact['Técnico'] = df_verif_compact['Técnico'].fillna('Sin asignar')
                
                st.dataframe(
                    df_verif_compact, 
                    use_container_width=True, 
                    hide_index=True
                )
        else:
            st.info("ℹ️ No hay reclamos verificados aún.")


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

        for idx, row in mis_reclamos.iterrows():
            renderizar_tarjeta(
                row, df_reclamos, ws_reclamos, 
                es_admin=False, ws_clientes=ws_clientes, df_clientes_raw=df_clientes_raw
            )

# =========================================================
# FLUJO PRINCIPAL (con auto-login por cookie)
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    saved_user = load_cookie("fusion_user")
    if saved_user:
        try:
            ws_reclamos, ws_clientes, ws_usuarios, ws_novedades = init_google_sheets()
            df_usuarios = pd.DataFrame(ws_usuarios.get_all_records())
            df_usuarios.columns = df_usuarios.columns.str.strip()
            user_row = df_usuarios[(df_usuarios['username'] == saved_user)]
            
            if not user_row.empty:
                rol = str(user_row.iloc[0]['rol']).strip()
                rol_lower = rol.lower()
                es_admin = rol_lower in ['admin', 'oficina', 'supervisor']
                
                st.session_state["authenticated"] = True
                st.session_state["user_name"] = user_row.iloc[0]['nombre']
                st.session_state["rol"] = rol
                st.session_state["es_admin"] = es_admin
            else:
                delete_cookie("fusion_user")
        except:
            pass

if st.session_state.authenticated:
    main_app()
else:
    login_screen()