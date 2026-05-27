import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
import time

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

    # Clientes
    df_c = df_clientes.rename(columns={'Nº Cliente': 'nro_cliente_cli', 'Latitud': 'lat', 'Longitud': 'lon'})
    df_c['nro_cliente_cli'] = df_c['nro_cliente_cli'].astype(str)
    df_c['lat'] = pd.to_numeric(df_c['lat'].astype(str).str.replace(',', '.'), errors='coerce')
    df_c['lon'] = pd.to_numeric(df_c['lon'].astype(str).str.replace(',', '.'), errors='coerce')
    coords = df_c[['nro_cliente_cli', 'lat', 'lon']].dropna(subset=['lat', 'lon'])

    # Reclamos
    df_r = df_reclamos.copy()
    df_r['Nº Cliente'] = df_r['Nº Cliente'].astype(str)
    df_r = df_r.merge(coords, left_on='Nº Cliente', right_on='nro_cliente_cli', how='left')

    # Fechas
    tz_argentina = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_argentina)
    df_r['Fecha_Parseada'] = pd.to_datetime(df_r['Fecha y hora'], format='%d/%m/%Y %H:%M', errors='coerce')
    df_r['Fecha_Parseada'] = df_r['Fecha_Parseada'].dt.tz_localize(tz_argentina)
    df_r['Horas_Transcurridas'] = (ahora - df_r['Fecha_Parseada']).dt.total_seconds() / 3600

    return df_r, df_usuarios

# =========================================================
# FUNCIÓN PARA DIBUJAR TARJETAS (Reutilizable)
# =========================================================
def renderizar_tarjeta(row, df_reclamos, ws_reclamos):
    sheet_row_num = row.name + 2 # El índice de pandas + 2
    horas = row['Horas_Transcurridas']

    # Badges
    badge = "🟢 Normal"
    if pd.notna(horas):
        if horas >= 48: badge = "🔴 +48 hs"
        elif horas >= 24: badge = "🟡 +24 hs"

    # Datos
    direccion = str(row.get('Dirección', 'Sin dirección')) if pd.notna(row.get('Dirección')) else 'Sin dirección'
    telefono = str(row.get('Teléfono', 'Sin teléfono')) if pd.notna(row.get('Teléfono')) else 'Sin teléfono'
    tipo_reclamo = str(row.get('Tipo de reclamo', ''))
    detalles = str(row.get('Detalles', '')) if pd.notna(row.get('Detalles')) and str(row.get('Detalles')) != '*' else ''
    precinto = str(row.get('N° de Precinto', '')) if pd.notna(row.get('N° de Precinto')) and str(row.get('N° de Precinto')) != '*' else ''
    sector = str(row.get('Sector', '')) if pd.notna(row.get('Sector')) else ''
    nombre_cliente = str(row.get('Nombre', ''))

    # Tiempo
    if pd.notna(horas):
        if horas < 1: texto_tiempo = f"hace {int(horas * 60)} min"
        elif horas < 24: texto_tiempo = f"hace {int(horas)} hs"
        else: texto_tiempo = f"hace {int(horas / 24)} días"
    else: texto_tiempo = "Fecha inválida"

    # Tarjeta
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
        if precinto: st.warning(f"🔒 Precinto: {precinto}")

        # Ubicación
        tiene_ubicacion = pd.notna(row.get('lat')) and pd.notna(row.get('lon'))
        if tiene_ubicacion:
            maps_url = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}"
            st.link_button("📍 Abrir ubicación en Google Maps", maps_url, use_container_width=True)
        else:
            st.caption("❌ Sin ubicación")

        # Verificar
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
                _, df_usuarios = cargar_datos()
                user_row = df_usuarios[(df_usuarios['username'] == username) & (df_usuarios['password'] == password)]
                
                if not user_row.empty:
                    rol = str(user_row.iloc[0]['rol']).strip()
                    rol_lower = rol.lower()
                    
                    # Determinar si es Admin o Técnico
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
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"### 👷 {st.session_state.user_name} ({'Admin' if es_admin else 'Técnico'})")
    with col2:
        if st.button("🚪 Salir"):
            st.session_state.authenticated = False
            st.rerun()

    st.divider()

    # Datos
    df_reclamos, _ = cargar_datos()
    ws_reclamos, _, _ = init_google_sheets()

    # Filtros base
    estados_excluidos = ["Resuelto", "Verificado"]
    mask_estado = ~df_reclamos['Estado'].isin(estados_excluidos)
    df_activos = df_reclamos[mask_estado].copy()
    
    # Llenar técnicos vacíos para evitar errores
    df_activos['Técnico'] = df_activos['Técnico'].fillna('Sin Asignar')

    # =====================================================
    # VISTA ADMIN
    # =====================================================
    if es_admin:
        st.markdown("### 👑 Panel de Administración")
        
        # Obtener lista de técnicos únicos en reclamos activos
        tecnicos_unicos = sorted(df_activos['Técnico'].unique().tolist())
        
        # Selector de técnico
        tecnico_seleccionado = st.selectbox(
            "Filtrar por Técnico", 
            ["Todos"] + tecnicos_unicos,
            index=0
        )
        
        # Filtrar DataFrame según selección
        if tecnico_seleccionado == "Todos":
            df_filtrado = df_activos.copy()
        else:
            df_filtrado = df_activos[df_activos['Técnico'] == tecnico_seleccionado].copy()

        # Ordenar
        df_filtrado = df_filtrado.sort_values(by='Horas_Transcurridas', ascending=False)
        
        st.markdown(f"**Reclamos en curso: {len(df_filtrado)}**")

        if df_filtrado.empty:
            st.success("🎉 No hay reclamos pendientes para este filtro.")
            return

        # Si seleccionó "Todos", agrupamos por técnico con acordeones
        if tecnico_seleccionado == "Todos":
            for tecnico, grupo in df_filtrado.groupby('Técnico'):
                with st.expander(f"👷 {tecnico} ({len(grupo)} reclamos)"):
                    for idx, row in grupo.iterrows():
                        renderizar_tarjeta(row, df_reclamos, ws_reclamos)
        else:
            # Si filtró por uno solo, mostramos tarjetas directas
            for idx, row in df_filtrado.iterrows():
                renderizar_tarjeta(row, df_reclamos, ws_reclamos)

    # =====================================================
    # VISTA TÉCNICO
    # =====================================================
    else:
        mask_tecnico = df_activos['Técnico'].str.contains(rol, case=False, na=False)
        mis_reclamos = df_activos[mask_tecnico].copy()

        # Ordenar por más viejos
        mis_reclamos = mis_reclamos.sort_values(by='Horas_Transcurridas', ascending=False)

        st.markdown(f"### 📋 Reclamos en curso: {len(mis_reclamos)}")

        if mis_reclamos.empty:
            st.success("🎉 No tenés reclamos pendientes.")
            return

        for idx, row in mis_reclamos.iterrows():
            renderizar_tarjeta(row, df_reclamos, ws_reclamos)

# =========================================================
# FLUJO PRINCIPAL
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if st.session_state.authenticated:
    main_app()
else:
    login_screen()