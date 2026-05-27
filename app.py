import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN DE PÁGINA (Optimizada para móvil) ---
st.set_page_config(page_title="Fusion - App Técnicos", page_icon="🔧", layout="centered", initial_sidebar_state="collapsed")

# ==========================================
# CONFIGURACIÓN DE CONEXIÓN
# ==========================================
SHEET_ID = "13R_3Mdr25Jd-nGhK7CxdcbKkFWLc0LPdYrOLOY8sZJo" # Tu mismo Sheet ID

WORKSHEET_RECLAMOS = "Reclamos"
WORKSHEET_CLIENTES = "Clientes"
WORKSHEET_USUARIOS = "usuarios"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# --- CONEXIÓN CON GOOGLE SHEETS ---
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

# --- CARGA DE DATOS ---
@st.cache_data(ttl=120) # Cache más corto (2 min) para que vean los cambios rápido
def cargar_datos():
    ws_reclamos, ws_clientes, ws_usuarios = init_google_sheets()
    
    df_reclamos = pd.DataFrame(ws_reclamos.get_all_records())
    df_clientes = pd.DataFrame(ws_clientes.get_all_records())
    df_usuarios = pd.DataFrame(ws_usuarios.get_all_records())
    
    # Limpiar y preparar datos de Clientes (para sacar Lat/Lon)
    df_c = df_clientes.rename(columns={'Nº Cliente': 'nro_cliente_cli', 'Latitud': 'lat', 'Longitud': 'lon'})
    df_c['nro_cliente_cli'] = df_c['nro_cliente_cli'].astype(str)
    df_c['lat'] = pd.to_numeric(df_c['lat'].astype(str).str.replace(',', '.'), errors='coerce')
    df_c['lon'] = pd.to_numeric(df_c['lon'].astype(str).str.replace(',', '.'), errors='coerce')
    coords = df_c[['nro_cliente_cli', 'lat', 'lon']].dropna(subset=['lat', 'lon'])

    # Limpiar datos de Reclamos
    df_r = df_reclamos.copy()
    df_r['Nº Cliente'] = df_r['Nº Cliente'].astype(str)
    
    # Cruce para obtener coordenadas
    df_r = df_r.merge(coords, left_on='Nº Cliente', right_on='nro_cliente_cli', how='left')

    return df_r, df_usuarios

# --- SISTEMA DE LOGIN ---
def login_screen():
    st.markdown("<h1 style='text-align: center;'>🔧 Fusion App Técnicos</h1>", unsafe_allow_html=True)
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
                    rol_tecnico = str(user_row.iloc[0]['rol']).strip()
                    if rol_tecnico and rol_tecnico.lower() not in ['admin', 'oficina', 'supervisor']: # Validación básica
                        st.session_state["authenticated"] = True
                        st.session_state["user_name"] = user_row.iloc[0]['nombre']
                        st.session_state["rol_tecnico"] = rol_tecnico
                        st.rerun()
                    else:
                        st.warning("Este usuario no es un técnico de campo.")
                else:
                    st.error("Usuario o contraseña incorrectos.")
            except Exception as e:
                st.error(f"Error al cargar datos: {e}")

# --- APLICACIÓN PRINCIPAL ---
def main_app():
    rol_tecnico = st.session_state.rol_tecnico
    
    # Header
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"### 👷 {st.session_state.user_name}")
    with col2:
        if st.button("🚪 Salir"):
            st.session_state.authenticated = False
            st.rerun()

    st.divider()

    # Cargar datos
    df_reclamos, _ = cargar_datos()
    ws_reclamos, _, _ = init_google_sheets()

    # FILTRO PRINCIPAL: Solo reclamos donde el técnico está asignado y NO están resueltos/verificados
    estados_excluidos = ["Resuelto", "Verificado"]
    
    # Lógica de búsqueda parcial (Ej: "CONEJO" encuentra "CONEJO, JUAN")
    # Ignoramos mayúsculas/minúsculas por si acaso
    mask_tecnico = df_reclamos['Técnico'].str.contains(rol_tecnico, case=False, na=False)
    mask_estado = ~df_reclamos['Estado'].isin(estados_excluidos)
    
    mis_reclamos = df_reclamos[mask_tecnico & mask_estado].copy()

    # Contador
    st.markdown(f"**Reclamos en curso: {len(mis_reclamos)}**")

    if mis_reclamos.empty:
        st.success("🎉 ¡Al día! No tenés reclamos pendientes por el momento.")
        return

    # Mostrar tarjetas de reclamos
    for idx, row in mis_reclamos.iterrows():
        # ID de fila real en Google Sheets (índice de pandas + 2 por encabezado y base 0)
        sheet_row_num = idx + 2 
        
        with st.container():
            # Cabecera de la tarjeta
            st.markdown(f"#### 🎫 Nº Cliente: {row['Nº Cliente']} - {row['Nombre']}")
            
            col_info, col_acciones = st.columns([3, 2])
            
            with col_info:
                st.markdown(f"**📍 Dirección:** {row['Dirección']}")
                st.markdown(f"**📞 Teléfono:** {row['Teléfono']}")
                st.markdown(f"**⚙️ Reclamo:** {row['Tipo de reclamo']}")
                if pd.notna(row.get('Detalles')) and str(row.get('Detalles', '')) != '*':
                    st.markdown(f"**📝 Detalles:** *{row['Detalles']}*")
                if pd.notna(row.get('N° de Precinto')) and str(row.get('N° de Precinto', '')) != '*':
                    st.markdown(f"**🔒 Precinto:** {row['N° de Precinto']}")

            with col_acciones:
                # Botón de Navegación (Maps / Waze)
                if pd.notna(row.get('lat')) and pd.notna(row.get('lon')):
                    lat = row['lat']
                    lon = row['lon']
                    maps_url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
                    st.markdown(f"[📍 Navegar al Cliente]({maps_url})", unsafe_allow_html=True)
                else:
                    st.markdown("❌ Sin ubicación")
                
                # Botón de Verificar (Estado -> Verificado)
                # Usamos un key único basado en el número de fila de la hoja
                if st.button("✅ Verificar Trabajo", key=f"verify_{sheet_row_num}", use_container_width=True):
                    try:
                        # Encontrar la columna "Estado" dinámicamente
                        col_idx = df_reclamos.columns.get_loc('Estado') + 1 # +1 porque gspread es base 1
                        ws_reclamos.update_cell(sheet_row_num, col_idx, "Verificado")
                        st.cache_data.clear() # Limpiar cache para que desaparezca
                        st.success("¡Reclamo Verificado! Actualizando lista...")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al actualizar: {e}")
            
            st.divider()

# --- FLUJO DE EJECUCIÓN ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if st.session_state.authenticated:
    main_app()
else:
    login_screen()