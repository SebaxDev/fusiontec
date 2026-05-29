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
# CONFIGURACIÓN DE PÁGINA
# =========================================================
st.set_page_config(
    page_title="Fusion - App Técnicos",
    page_icon="🔧",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# =========================================================
# CONFIGURACIÓN GOOGLE SHEETS
# =========================================================
SHEET_ID = "13R_3Mdr25Jd-nGhK7CxdcbKkFWLc0LPdYrOLOY8sZJo"

WORKSHEET_RECLAMOS = "Reclamos"
WORKSHEET_CLIENTES = "Clientes"
WORKSHEET_USUARIOS = "usuarios"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
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
        ws_reclamos = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_RECLAMOS)
        ws_clientes = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_CLIENTES)
        ws_usuarios = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_USUARIOS)
        return ws_reclamos, ws_clientes, ws_usuarios
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        st.stop()

# =========================================================
# CARGA DE DATOS
# =========================================================
@st.cache_data(ttl=120)
def cargar_datos():
    ws_reclamos, ws_clientes, ws_usuarios = init_google_sheets()
    df_reclamos = pd.DataFrame(ws_reclamos.get_all_records())
    df_clientes = pd.DataFrame(ws_clientes.get_all_records())
    df_usuarios = pd.DataFrame(ws_usuarios.get_all_records())

    df_clientes_raw = df_clientes.copy()

    # Clientes - Extraer Coordenadas y Precinto
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

    # Reclamos
    df_r = df_reclamos.copy()
    df_r['Nº Cliente'] = df_r['Nº Cliente'].astype(str)
    
    df_r = df_r.merge(datos_cliente, left_on='Nº Cliente', right_on='nro_cliente_cli', how='left')

    # Fechas
    tz_argentina = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_argentina)
    df_r['Fecha_Parseada'] = pd.to_datetime(df_r['Fecha y hora'], format='%d/%m/%Y %H:%M', errors='coerce')
    df_r['Fecha_Parseada'] = df_r['Fecha_Parseada'].dt.tz_localize(tz_argentina)
    df_r['Horas_Transcurridas'] = (ahora - df_r['Fecha_Parseada']).dt.total_seconds() / 3600

    # Limpieza
    df_r['Estado_Limpio'] = df_r['Estado'].astype(str).str.strip()
    df_r['Tecnico_Limpio'] = df_r['Técnico'].astype(str).str.strip()
    df_r['Tecnico_Limpio'] = df_r['Tecnico_Limpio'].replace('', np.nan)

    return df_r, df_usuarios, df_clientes_raw

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

        if es_admin and ws_clientes is not None and df_clientes_raw is not None:
            df_cl = df_clientes_raw.copy()
            df_cl['Nº Cliente'] = df_cl['Nº Cliente'].astype(str).str.strip()
            cliente_match = df_cl[df_cl['Nº Cliente'] == nro_cliente]
            
            if not cliente_match.empty:
                cliente_fila = cliente_match.index[0] + 2
                
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

        if st.button("✅ Verificar Trabajo", key=f"verify_{sheet_row_num}", use_container_width=True):
            try:
                col_idx = df_reclamos.columns.get_loc('Estado') + 1
                ws_reclamos.update_cell(sheet_row_num, col_idx, "Verificado")
                st.cache_data.clear()
                st.success("¡Reclamo verificado!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Error al actualizar: {e}")

# =========================================================
# GENERADOR DE PDF
# =========================================================
class PDFReporte(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, f'Reclamos en Curso/Verificados - {datetime.now().strftime("%d/%m/%Y")}', 0, 1, 'C')
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
        block_height = 7 + (count_tec * 5)

        if current_y + block_height > bottom_limit:
            current_col += 1
            if current_col > 1:
                pdf.add_page()
                current_col = 0
            current_x = cols_x[current_col]
            current_y = margin_y

        tecnico_safe = tecnico.encode('latin-1', 'replace').decode('latin-1')
        pdf.set_xy(current_x, current_y)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(col_width, 5, f"Técnico: {tecnico_safe} ({count_tec})", 0, 1)
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
                _, df_usuarios, _ = cargar_datos()
                user_row = df_usuarios[(df_usuarios['username'] == username) & (df_usuarios['password'] == password)]
                
                if not user_row.empty:
                    rol = str(user_row.iloc[0]['rol']).strip()
                    rol_lower = rol.lower()
                    
                    if rol_lower in ['admin', 'oficina', 'supervisor']:
                        es_admin = True
                    else:
                        es_admin = False

                    st.session_state["authenticated"] = True
                    st.session_state["user_name"] = user_row.iloc[0]['nombre']
                    st.session_state["rol"] = rol
                    st.session_state["es_admin"] = es_admin
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
            st.session_state.authenticated = False
            st.rerun()

    st.divider()

    # Datos
    df_reclamos, _, df_clientes_raw = cargar_datos()
    ws_reclamos, ws_clientes, _ = init_google_sheets()

    mask_tecnico_asignado = df_reclamos['Tecnico_Limpio'].notna()

    # =====================================================
    # VISTA ADMIN
    # =====================================================
    if es_admin:
        st.markdown("### 👑 Panel de Administración")
        
        # --- HERRAMIENTAS ADMIN ---
        with st.container(border=True):
            st.markdown("**⚙️ Herramientas de Gestión**")
            col_p1, col_p2, col_p3 = st.columns(3)
            
            with col_p1:
                if st.button("📄 Generar PDF", use_container_width=True):
                    with st.spinner("Generando PDF..."):
                        try:
                            estados_pdf = ["En curso", "Verificado"]
                            mask_pdf = df_reclamos['Estado_Limpio'].isin(estados_pdf)
                            df_activos_pdf = df_reclamos[mask_pdf & mask_tecnico_asignado].copy()
                            
                            pdf_bytes = generar_pdf(df_activos_pdf, datetime.now().strftime("%d/%m/%Y"))
                            st.download_button(
                                label="⬇️ Descargar PDF",
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
                        mask_verificados = df_reclamos['Estado_Limpio'] == "Verificado"
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
                        mask_en_curso = df_reclamos['Estado_Limpio'] == "En curso"
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
        
        st.divider()

        # --- CONTADORES POR TÉCNICO ---
        mask_verificados_tec = (df_reclamos['Estado_Limpio'] == "Verificado") & mask_tecnico_asignado
        verificados_por_tecnico = df_reclamos[mask_verificados_tec].groupby('Tecnico_Limpio').size().to_dict()

        # --- LISTADO ADMIN (Solo "En curso") ---
        estados_display = ["En curso"]
        mask_estado_display = df_reclamos['Estado_Limpio'].isin(estados_display)
        df_activos_display = df_reclamos[mask_estado_display & mask_tecnico_asignado].copy()

        if df_activos_display.empty:
            st.success("🎉 No hay reclamos En curso con técnico asignado.")
            return

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
            renderizar_tarjeta(row, df_reclamos, ws_reclamos, es_admin=False)

# =========================================================
# FLUJO PRINCIPAL
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if st.session_state.authenticated:
    main_app()
else:
    login_screen()