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
from selenium.common.exceptions import TimeoutException
from mysql.connector.pooling import MySQLConnectionPool
from app.config import settings

class TiktokScraperService:
    def __init__(self, app_user_id: int, tk_username: str, tk_password: str):
        self.app_user_id = app_user_id
        self.tk_user = tk_username
        self.tk_password = tk_password
        self.db_batch_size = 500
        self.table_snapshot = 'app_tk_followers_snapshot'
        self.table_lost = 'app_tk_followers_lost'
        self.pool = None

        self.session_dir = os.path.join(os.getcwd(), "chrome_sessions_tiktok", f"user_{self.app_user_id}")
        os.makedirs(self.session_dir, exist_ok=True)

        self._init_pool()

    def _init_pool(self):
        try:
            self.pool = MySQLConnectionPool(
                pool_name=f'tk_pool_{self.app_user_id}',
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
        if not self.pool:
            self._init_pool()
        return self.pool.get_connection() if self.pool else None

    def _tiene_sesion_guardada(self):
        cookies_file = os.path.join(self.session_dir, "Default", "Cookies")
        network_file = os.path.join(self.session_dir, "Default", "Network", "Cookies")
        return (os.path.exists(network_file) and os.path.getsize(network_file) > 10_000) or \
               (os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 10_000)

    def _hacer_scroll(self, driver, scroll_box, veces=5, pausa=1.5):
        for _ in range(veces):
            try:
                driver.execute_script("""
                    var box = arguments[0]; var items = box.querySelectorAll('li');
                    if (items.length > 0) { items[items.length - 1].scrollIntoView(); }
                    box.scrollTop += arguments[1];
                """, scroll_box, random.randint(600, 900))
            except:
                try:
                    driver.execute_script("arguments[0].scrollTop += arguments[1]", scroll_box, random.randint(600, 900))
                except:
                    pass
            time.sleep(pausa)

    def _obtener_numero_seguidores(self, driver):
        try:
            time.sleep(2)
            el = driver.find_element(By.XPATH, "//strong[@title='Followers' or @data-e2e='followers-count']")
            txt = el.get_attribute('title') or el.text
            return int(''.join(filter(str.isdigit, txt)))
        except:
            return None

    def _chunks(self, lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def _obtener_snapshot_actual(self, conn):
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(f"SELECT username, full_name FROM {self.table_snapshot} WHERE app_user_id = %s", (self.app_user_id,))
            return {r['username']: r['full_name'] for r in cursor.fetchall()}

    def _obtener_usuarios_en_lost(self, conn, usernames: set):
        if not usernames:
            return set()
        placeholders = ', '.join(['%s'] * len(usernames))
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT username FROM {self.table_lost} WHERE app_user_id = %s AND username IN ({placeholders})",
                [self.app_user_id] + list(usernames)
            )
            return {r[0] for r in cursor.fetchall()}

    def _insertar_en_snapshot(self, conn, seguidores: list):
        if not seguidores:
            return
        query = f"INSERT INTO {self.table_snapshot} (app_user_id, username, full_name, scraped_at) VALUES (%s, %s, %s, %s)"
        with conn.cursor() as cursor:
            for batch in self._chunks(seguidores, self.db_batch_size):
                valores = [(self.app_user_id, s['username'], s['full_name'], s['scraped_at']) for s in batch]
                cursor.executemany(query, valores)
                conn.commit()

    def _eliminar_de_snapshot(self, conn, usernames: set):
        if not usernames:
            return
        with conn.cursor() as cursor:
            for batch in self._chunks(list(usernames), self.db_batch_size):
                placeholders = ', '.join(['%s'] * len(batch))
                cursor.execute(
                    f"DELETE FROM {self.table_snapshot} WHERE app_user_id = %s AND username IN ({placeholders})",
                    [self.app_user_id] + batch
                )
                conn.commit()

    def _insertar_en_lost(self, conn, perdidos: list):
        if not perdidos:
            return
        query = f"INSERT INTO {self.table_lost} (app_user_id, username, full_name, fecha_perdida) VALUES (%s, %s, %s, %s)"
        with conn.cursor() as cursor:
            for batch in self._chunks(perdidos, self.db_batch_size):
                valores = [(self.app_user_id, p['username'], p['full_name'], p['fecha_perdida']) for p in batch]
                cursor.executemany(query, valores)
                conn.commit()

    def _eliminar_de_lost(self, conn, usernames: set):
        if not usernames:
            return
        with conn.cursor() as cursor:
            for batch in self._chunks(list(usernames), self.db_batch_size):
                placeholders = ', '.join(['%s'] * len(batch))
                cursor.execute(
                    f"DELETE FROM {self.table_lost} WHERE app_user_id = %s AND username IN ({placeholders})",
                    [self.app_user_id] + batch
                )
                conn.commit()

    def _build_driver(self):
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={self.session_dir}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--headless=new")

        # En Docker usamos el chromedriver del sistema, alineado con el Chrome instalado.
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=chrome_options)

    def run_extraction(self):
        conn = self._conectar_mysql()
        if not conn:
            return "Database connection failed"

        driver = self._build_driver()

        try:
            driver.get("https://www.tiktok.com/login/phone-or-email/email")
            time.sleep(5)

            try:
                user_input = driver.find_elements(By.XPATH, "//input[@type='text' and @name='username']")
                if user_input:
                    pass_input = driver.find_element(By.XPATH, "//input[@type='password']")
                    user_input[0].send_keys(self.tk_user)
                    time.sleep(1)
                    pass_input.send_keys(self.tk_password)
                    time.sleep(1)
                    login_btn = driver.find_element(By.XPATH, "//button[@data-e2e='login-button']")
                    login_btn.click()
                    time.sleep(10)
            except Exception:
                pass

            driver.get(f"https://www.tiktok.com/@{self.tk_user}")
            time.sleep(6)

            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//strong[@data-e2e='followers-count']"))
                )
            except TimeoutException:
                return "Fallo en la autenticacion de TikTok. Posible CAPTCHA requerido."

            total_seg = self._obtener_numero_seguidores(driver) or 0

            try:
                followers_btn = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, "//strong[@data-e2e='followers-count']"))
                )
                followers_btn.click()
                time.sleep(4)
            except TimeoutException:
                return "No se pudo abrir la lista de seguidores"

            try:
                scroll_box = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'DivUserListContainer')]"))
                )
            except TimeoutException:
                return "No se encontro el modal de seguidores"

            seguidores_encontrados = {}
            fecha_actual = datetime.now().replace(microsecond=0)
            intentos_sin_cambio = 0
            max_intentos = max(8, min(30, total_seg // 50)) if total_seg else 10

            def extraer_visibles():
                try:
                    items = scroll_box.find_elements(By.XPATH, ".//li[.//p[contains(@class,'PUniqueId')]]")
                    for item in items:
                        try:
                            username = item.find_element(By.XPATH, ".//p[contains(@class,'PUniqueId')]").text.strip()
                            try:
                                full_name = item.find_element(By.XPATH, ".//span[contains(@class,'SpanNickname')]").text.strip()
                            except:
                                full_name = ""
                            if username and username not in seguidores_encontrados:
                                seguidores_encontrados[username] = full_name
                        except:
                            continue
                except:
                    pass

            extraer_visibles()
            while intentos_sin_cambio < max_intentos:
                antes = len(seguidores_encontrados)
                self._hacer_scroll(driver, scroll_box, veces=5, pausa=1.5)
                time.sleep(3)
                extraer_visibles()
                ahora = len(seguidores_encontrados)
                if ahora > antes:
                    intentos_sin_cambio = 0
                else:
                    intentos_sin_cambio += 1
                if total_seg and ahora >= total_seg:
                    break

            seguidores_hoy = {u: fn for u, fn in seguidores_encontrados.items() if u and len(u) > 1}
            snapshot_mysql = self._obtener_snapshot_actual(conn)
            seguidores_mysql = set(snapshot_mysql.keys())

            if not seguidores_mysql:
                todos = [{"username": u, "full_name": fn, "scraped_at": fecha_actual} for u, fn in seguidores_hoy.items()]
                self._insertar_en_snapshot(conn, todos)
                return "Primera ejecucion completada. Todos guardados."

            usernames_nuevos = set(seguidores_hoy.keys()) - seguidores_mysql
            if usernames_nuevos:
                nuevos = [{"username": u, "full_name": seguidores_hoy[u], "scraped_at": fecha_actual} for u in usernames_nuevos]
                self._insertar_en_snapshot(conn, nuevos)
                en_lost = self._obtener_usuarios_en_lost(conn, usernames_nuevos)
                if en_lost:
                    self._eliminar_de_lost(conn, en_lost)

            usernames_perdidos = seguidores_mysql - set(seguidores_hoy.keys())
            if usernames_perdidos:
                self._eliminar_de_snapshot(conn, usernames_perdidos)
                perdidos = [{"username": u, "full_name": snapshot_mysql.get(u, ""), "fecha_perdida": fecha_actual} for u in usernames_perdidos]
                self._insertar_en_lost(conn, perdidos)

            return f"TikTok Scraping completado. Encontrados: {len(seguidores_hoy)}. Nuevos: {len(usernames_nuevos)}. Perdidos: {len(usernames_perdidos)}"

        except Exception as e:
            return f"Error general durante el scraping: {str(e)}"
        finally:
            driver.quit()
            conn.close()