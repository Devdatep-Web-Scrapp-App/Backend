import os
import time
import random
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from mysql.connector.pooling import MySQLConnectionPool
from app.config import settings

class InstagramScraperService:
    def __init__(self, app_user_id: int, ig_username: str, ig_password: str):
        self.app_user_id = app_user_id
        self.ig_user = ig_username
        self.ig_password = ig_password
        self.db_batch_size = 500
        # Usamos las nuevas tablas
        self.table_snapshot = 'app_ig_followers_snapshot'
        self.table_lost = 'app_ig_followers_lost'
        self.pool = None
        
        # Cada usuario de tu app tiene su propia carpeta de sesión de Chrome
        self.session_dir = os.path.join(os.getcwd(), "chrome_sessions", f"user_{self.app_user_id}")
        os.makedirs(self.session_dir, exist_ok=True)
        
        self._init_pool()

    def _init_pool(self):
        try:
            self.pool = MySQLConnectionPool(
                pool_name=f'ig_pool_{self.app_user_id}',
                pool_size=2,
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                database=settings.DB_NAME
            )
        except Exception as e:
            print(f'Error creando pool MySQL: {e}')

    def _conectar_mysql(self):
        if not self.pool: self._init_pool()
        return self.pool.get_connection() if self.pool else None

    def _tiene_sesion_guardada(self):
        cookies_file = os.path.join(self.session_dir, "Default", "Cookies")
        network_file = os.path.join(self.session_dir, "Default", "Network", "Cookies")
        if os.path.exists(network_file) and os.path.getsize(network_file) > 10_000: return True
        if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 10_000: return True
        return False

    def _hacer_scroll(self, driver, scroll_box, veces=5, pausa=1.5):
        for _ in range(veces):
            try:
                driver.execute_script("""
                    var box = arguments[0]; var items = box.querySelectorAll('div, li');
                    if (items.length > 0) { items[items.length - 1].scrollIntoView(); }
                    box.scrollTop += arguments[1];
                """, scroll_box, random.randint(600, 900))
            except:
                try: driver.execute_script("arguments[0].scrollTop += arguments[1]", scroll_box, random.randint(600, 900))
                except: pass
            time.sleep(pausa)

    def _esperar_carga(self, driver, timeout=8):
        try: WebDriverWait(driver, timeout).until(EC.invisibility_of_element_located((By.XPATH, "//div[@role='progressbar']")))
        except: pass

    def _obtener_numero_seguidores(self, driver):
        try:
            time.sleep(2)
            el = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]/span")))
            txt = el.get_attribute('title') or el.text
            return int(''.join(filter(str.isdigit, txt)))
        except: return None

    def _chunks(self, lst, n):
        for i in range(0, len(lst), n): yield lst[i:i +n]

    # --- CONSULTAS SQL ACTUALIZADAS PARA MULTI-TENANT (Filtro por app_user_id) ---

    def _obtener_snapshot_actual(self, conn):
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(f"SELECT username, full_name FROM {self.table_snapshot} WHERE app_user_id = %s", (self.app_user_id,))
            return {r['username']: r['full_name'] for r in cursor.fetchall()}

    def _obtener_usuarios_en_lost(self, conn, usernames: set):
        if not usernames: return set()
        placeholders = ', '.join(['%s'] * len(usernames))
        with conn.cursor() as cursor:
            query = f"SELECT username FROM {self.table_lost} WHERE app_user_id = %s AND username IN ({placeholders})"
            params = [self.app_user_id] + list(usernames)
            cursor.execute(query, params)
            return {r[0] for r in cursor.fetchall()}

    def _insertar_en_snapshot(self, conn, seguidores: list):
        if not seguidores: return
        query = f"INSERT INTO {self.table_snapshot} (app_user_id, username, full_name, scraped_at) VALUES (%s, %s, %s, %s)"
        with conn.cursor() as cursor:
            for batch in self._chunks(seguidores, self.db_batch_size):
                valores = [(self.app_user_id, s['username'], s['full_name'], s['scraped_at']) for s in batch]
                cursor.executemany(query, valores)
                conn.commit()

    def _eliminar_de_snapshot(self, conn, usernames: set):
        if not usernames: return
        with conn.cursor() as cursor:
            for batch in self._chunks(list(usernames), self.db_batch_size):
                placeholders = ', '.join(['%s'] * len(batch))
                query = f"DELETE FROM {self.table_snapshot} WHERE app_user_id = %s AND username IN ({placeholders})"
                params = [self.app_user_id] + batch
                cursor.execute(query, params)
                conn.commit()

    def _insertar_en_lost(self, conn, perdidos: list):
        if not perdidos: return
        query = f"INSERT INTO {self.table_lost} (app_user_id, username, full_name, fecha_perdida) VALUES (%s, %s, %s, %s)"
        with conn.cursor() as cursor:
            for batch in self._chunks(perdidos, self.db_batch_size):
                valores = [(self.app_user_id, p['username'], p['full_name'], p['fecha_perdida']) for p in batch]
                cursor.executemany(query, valores)
                conn.commit()

    def _eliminar_de_lost(self, conn, usernames: set):
        if not usernames: return
        with conn.cursor() as cursor:
            for batch in self._chunks(list(usernames), self.db_batch_size):
                placeholders = ', '.join(['%s'] * len(batch))
                query = f"DELETE FROM {self.table_lost} WHERE app_user_id = %s AND username IN ({placeholders})"
                params = [self.app_user_id] + batch
                cursor.execute(query, params)
                conn.commit()

    # --- LÓGICA DE SELENIUM Y LOGIN AUTOMÁTICO ---

    def run_extraction(self):
        conn = self._conectar_mysql()
        if not conn: return "Database connection failed"

        headless = self._tiene_sesion_guardada()
        
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={self.session_dir}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # En producción siempre debería ir headless. 
        # Aquí lo forzamos a headless si ya tiene sesión, o visible si no la tiene para debugear, 
        # pero en Docker todo es headless.
        chrome_options.add_argument("--headless=new") 

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            # 1. FLUJO DE LOGIN AUTOMATIZADO
            driver.get("https://www.instagram.com/")
            time.sleep(5)
            
            # Verificar si estamos en la página de login
            try:
                login_btn = driver.find_elements(By.XPATH, "//button[@type='submit']")
                if login_btn:
                    print(f"[{self.ig_user}] Sesión no detectada. Intentando login automático...")
                    user_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username")))
                    pass_input = driver.find_element(By.NAME, "password")
                    
                    user_input.send_keys(self.ig_user)
                    time.sleep(1)
                    pass_input.send_keys(self.ig_password)
                    time.sleep(1)
                    pass_input.submit()
                    time.sleep(8)
                    
                    # Intentar saltar el modal de "Guardar información de inicio de sesión"
                    try:
                        save_info_btn = driver.find_element(By.XPATH, "//button[text()='Guardar información']")
                        save_info_btn.click()
                        time.sleep(3)
                    except: pass
            except Exception as e:
                print(f"[{self.ig_user}] Posiblemente ya logueado o error en login: {e}")

            # 2. IR AL PERFIL Y SACAR SEGUIDORES
            driver.get(f"https://www.instagram.com/{self.ig_user}/")
            time.sleep(6)
            
            # Verificar que entramos bien al perfil
            try:
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]")))
            except TimeoutException:
                return "Fallo en la autenticación. Instagram podría estar pidiendo 2FA o CAPTCHA."

            total_seg = self._obtener_numero_seguidores(driver) or 0
            
            try:
                btn = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]")))
                btn.click()
                time.sleep(5)
            except TimeoutException: return "No se pudo abrir la lista de seguidores"

            try:
                dialog = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']")))
                scroll_box = dialog.find_element(By.XPATH, ".//div[contains(@style, 'overflow: hidden auto')]")
            except TimeoutException: return "No se encontró el modal de scroll"

            seguidores_encontrados = {}
            fecha_actual = datetime.now().replace(microsecond=0)
            intentos_sin_cambio = 0
            max_intentos = max(8, min(30, total_seg // 50)) if total_seg else 10

            def extraer_visibles():
                try:
                    elementos = scroll_box.find_elements(By.XPATH, ".//div[contains(@class, 'x1qnrgzn')]")
                    for el in elementos:
                        try:
                            username = el.find_element(By.XPATH, ".//span[contains(@class, '_ap3a')]").text.strip()
                            try: full_name = el.find_element(By.XPATH, ".//span[contains(@class, 'x1lliihq') and contains(@class, 'x193iq5w')]").text.strip()
                            except: full_name = ""
                            if username and username not in seguidores_encontrados:
                                seguidores_encontrados[username] = full_name
                        except: continue
                except: pass

            extraer_visibles()
            while intentos_sin_cambio < max_intentos:
                antes = len(seguidores_encontrados)
                self._hacer_scroll(driver, scroll_box, veces=3, pausa=1.0)
                self._esperar_carga(driver)
                time.sleep(2)
                extraer_visibles()
                ahora = len(seguidores_encontrados)
                
                if ahora > antes: intentos_sin_cambio = 0
                else: intentos_sin_cambio += 1
                if total_seg and ahora >= total_seg: break
                time.sleep(0.5)

            seguidores_hoy = {u: fn for u, fn in seguidores_encontrados.items() if u and len(u) > 1}
            snapshot_mysql = self._obtener_snapshot_actual(conn)
            seguidores_mysql = set(snapshot_mysql.keys())

            if not seguidores_mysql:
                todos = [{"username": u, "full_name": fn, "scraped_at": fecha_actual} for u, fn in seguidores_hoy.items()]
                self._insertar_en_snapshot(conn, todos)
                return "Primera ejecución completada. Todos guardados."

            usernames_nuevos = set(seguidores_hoy.keys()) - seguidores_mysql
            if usernames_nuevos:
                nuevos = [{"username": u, "full_name": seguidores_hoy[u], "scraped_at": fecha_actual} for u in usernames_nuevos]
                self._insertar_en_snapshot(conn, nuevos)
                en_lost = self._obtener_usuarios_en_lost(conn, usernames_nuevos)
                if en_lost: self._eliminar_de_lost(conn, en_lost)

            usernames_perdidos = seguidores_mysql - set(seguidores_hoy.keys())
            if usernames_perdidos:
                self._eliminar_de_snapshot(conn, usernames_perdidos)
                perdidos = [{"username": u, "full_name": snapshot_mysql.get(u, ""), "fecha_perdida": fecha_actual} for u in usernames_perdidos]
                self._insertar_en_lost(conn, perdidos)

            return f"Scraping completado. Encontrados: {len(seguidores_hoy)}. Nuevos: {len(usernames_nuevos)}. Perdidos: {len(usernames_perdidos)}"
            
        except Exception as e:
            return f"Error general durante el scraping: {str(e)}"
        finally:
            driver.quit()
            conn.close()