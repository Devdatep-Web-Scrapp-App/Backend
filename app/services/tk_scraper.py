import os
import time
import random
import glob
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


class TiktokScraperService:
    def __init__(self, app_user_id: int, tk_username: str, tk_password: str):
        self.app_user_id = app_user_id
        self.tk_user = tk_username
        self.tk_password = tk_password
        self.db_batch_size = 500
        self.table_snapshot = 'app_tk_followers_snapshot'
        self.table_lost = 'app_tk_followers_lost'
        self.pool = None

        self.session_dir = os.path.join(
            os.getcwd(), "chrome_sessions_tiktok", f"user_{self.app_user_id}"
        )
        os.makedirs(self.session_dir, exist_ok=True)
        self._init_pool()

    # ------------------------------------------------------------------ #
    #  Pool MySQL & Consultas BD                                          #
    # ------------------------------------------------------------------ #

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
            print(f'Error creando pool MySQL para TikTok: {e}')

    def _conectar_mysql(self):
        if not self.pool:
            self._init_pool()
        return self.pool.get_connection() if self.pool else None

    @staticmethod
    def _chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def _obtener_snapshot_actual(self, conn):
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                f"SELECT username, full_name FROM {self.table_snapshot} WHERE app_user_id = %s",
                (self.app_user_id,)
            )
            return {r['username']: r['full_name'] for r in cursor.fetchall()}

    def _obtener_usuarios_en_lost(self, conn, usernames: set):
        if not usernames:
            return set()
        placeholders = ', '.join(['%s'] * len(usernames))
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT username FROM {self.table_lost} "
                f"WHERE app_user_id = %s AND username IN ({placeholders})",
                [self.app_user_id] + list(usernames)
            )
            return {r[0] for r in cursor.fetchall()}

    def _insertar_en_snapshot(self, conn, seguidores: list):
        if not seguidores:
            return
        query = (
            f"INSERT INTO {self.table_snapshot} "
            f"(app_user_id, username, full_name, scraped_at) VALUES (%s, %s, %s, %s)"
        )
        with conn.cursor() as cursor:
            for batch in self._chunks(seguidores, self.db_batch_size):
                valores = [
                    (self.app_user_id, s['username'], s['full_name'], s['scraped_at'])
                    for s in batch
                ]
                cursor.executemany(query, valores)
            conn.commit()

    def _eliminar_de_snapshot(self, conn, usernames: set):
        if not usernames:
            return
        with conn.cursor() as cursor:
            for batch in self._chunks(list(usernames), self.db_batch_size):
                placeholders = ', '.join(['%s'] * len(batch))
                cursor.execute(
                    f"DELETE FROM {self.table_snapshot} "
                    f"WHERE app_user_id = %s AND username IN ({placeholders})",
                    [self.app_user_id] + batch
                )
            conn.commit()

    def _insertar_en_lost(self, conn, perdidos: list):
        if not perdidos:
            return
        query = (
            f"INSERT INTO {self.table_lost} "
            f"(app_user_id, username, full_name, fecha_perdida) VALUES (%s, %s, %s, %s)"
        )
        with conn.cursor() as cursor:
            for batch in self._chunks(perdidos, self.db_batch_size):
                valores = [
                    (self.app_user_id, p['username'], p['full_name'], p['fecha_perdida'])
                    for p in batch
                ]
                cursor.executemany(query, valores)
            conn.commit()

    def _eliminar_de_lost(self, conn, usernames: set):
        if not usernames:
            return
        with conn.cursor() as cursor:
            for batch in self._chunks(list(usernames), self.db_batch_size):
                placeholders = ', '.join(['%s'] * len(batch))
                cursor.execute(
                    f"DELETE FROM {self.table_lost} "
                    f"WHERE app_user_id = %s AND username IN ({placeholders})",
                    [self.app_user_id] + batch
                )
            conn.commit()

    # ------------------------------------------------------------------ #
    #  Utilidades Selenium                                                #
    # ------------------------------------------------------------------ #

    def _tiene_sesion_guardada(self):
        cookies_file = os.path.join(self.session_dir, "Default", "Cookies")
        network_file = os.path.join(self.session_dir, "Default", "Network", "Cookies")
        if os.path.exists(network_file) and os.path.getsize(network_file) > 10_000:
            return True
        if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 10_000:
            return True
        return False

    @staticmethod
    def _hacer_scroll(driver, scroll_box, veces=5, pausa=1.5):
        for _ in range(veces):
            try:
                driver.execute_script("""
                    var box   = arguments[0];
                    var items = box.querySelectorAll('li');
                    if (items.length > 0) items[items.length - 1].scrollIntoView();
                    box.scrollTop += arguments[1];
                """, scroll_box, random.randint(600, 900))
            except Exception:
                try:
                    driver.execute_script(
                        "arguments[0].scrollTop += arguments[1]",
                        scroll_box, random.randint(600, 900)
                    )
                except Exception:
                    pass
            time.sleep(pausa)

    @staticmethod
    def _obtener_numero_seguidores(driver):
        try:
            time.sleep(2)
            el = driver.find_element(By.XPATH, "//strong[@title='Followers' or @data-e2e='followers-count']")
            txt = el.get_attribute('title') or el.text
            return int(''.join(filter(str.isdigit, txt)))
        except Exception:
            return None

    @staticmethod
    def _login_popup_visible(driver) -> bool:
        """Devuelve True si el loginContainer de TikTok está visible en pantalla."""
        try:
            lc = driver.find_element(By.ID, "loginContainer")
            return lc.is_displayed()
        except Exception:
            return False

    @staticmethod
    def _verificar_sesion(driver) -> bool:
        """
        Espera hasta 8 segundos a que aparezca el loginContainer.
        Si aparece → sesión inválida. Si no aparece en ese tiempo → sesión activa.
        """
        try:
            lc = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.ID, "loginContainer"))
            )
            return not lc.is_displayed()
        except TimeoutException:
            # loginContainer no apareció: sesión activa
            return True

    @staticmethod
    def _get_driver_path():
        os.environ["WDM_ARCH"] = "64"
        driver_path = ChromeDriverManager().install()
        if not driver_path.endswith(".exe"):
            exe_candidates = glob.glob(
                os.path.join(os.path.dirname(driver_path), "chromedriver*.exe")
            )
            if exe_candidates:
                driver_path = exe_candidates[0]
        return driver_path

    _STEALTH_JS = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['es-PE', 'es', 'en-US', 'en']});
        Object.keys(window).forEach(key => {
            if (key.startsWith('$cdc_') || key.startsWith('$chrome_')) delete window[key];
        });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
    """

    def _aplicar_stealth(self, driver):
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": self._STEALTH_JS})

    def _base_chrome_options(self) -> Options:
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={self.session_dir}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--lang=es-PE")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        )
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        return chrome_options

    def _build_driver(self, headless: bool = True):
        chrome_options = self._base_chrome_options()
        if headless:
            chrome_options.add_argument("--headless=new")
        else:
            chrome_options.add_argument("--start-maximized")

        service = Service(self._get_driver_path())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        self._aplicar_stealth(driver)
        return driver

    # ------------------------------------------------------------------ #
    #  Setup de sesión (login manual via QR)                             #
    # ------------------------------------------------------------------ #

    def setup_session(self):
        driver = self._build_driver(headless=False)
        try:
            driver.get("https://www.tiktok.com/login")
            print(f"[{self.tk_user}] Inicia sesion manualmente con usuario y contrasena en el navegador.")
            print(f"[{self.tk_user}] Cuando hayas iniciado sesion y veas tu feed, presiona ENTER aqui.")
            input(">>> ")

            # Verificar que el login fue exitoso
            try:
                lc = driver.find_element(By.ID, "loginContainer")
                if lc.is_displayed():
                    print(f"[{self.tk_user}] El login no se completo. Intenta nuevamente.")
                    return
            except Exception:
                pass

            print(f"[{self.tk_user}] Sesion de TikTok guardada correctamente.")
            time.sleep(3)
        except Exception as e:
            print(f"[{self.tk_user}] Error durante setup: {e}")
        finally:
            driver.quit()

    # ------------------------------------------------------------------ #
    #  Extracción principal                                               #
    # ------------------------------------------------------------------ #

    def run_extraction(self):
        conn = self._conectar_mysql()
        if not conn:
            return "Database connection failed"

        if not self._tiene_sesion_guardada():
            return "No hay sesion de TikTok guardada. Llama primero al endpoint /scraper/setup-tiktok."

        driver = self._build_driver(headless=True)

        try:
            # 1. NAVEGAR AL PERFIL
            driver.get(f"https://www.tiktok.com/@{self.tk_user}")
            print(f"[{self.tk_user}] Accediendo al perfil...")
            time.sleep(6)

            # 2. VERIFICAR SESIÓN
            # Espera a que aparezca loginContainer: si aparece = sesión expirada
            if not self._verificar_sesion(driver):
                return "La sesion de TikTok expiro. Vuelve a ejecutar /scraper/setup-tiktok."
            print(f"[{self.tk_user}] Sesion activa, continuando...")

            # 3. TOTAL DE SEGUIDORES
            total_seg = self._obtener_numero_seguidores(driver) or 0
            print(f"[{self.tk_user}] Total segun perfil: {total_seg or 'desconocido'}")

            # 4. ABRIR MODAL DE SEGUIDORES (JS click para evitar intercepción)
            try:
                followers_btn = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//strong[@data-e2e='followers-count']")
                    )
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", followers_btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", followers_btn)
                time.sleep(4)
            except TimeoutException:
                return "No se pudo abrir la lista de seguidores"

            # 5. UBICAR CAJA DE SCROLL
            try:
                scroll_box = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//div[contains(@class,'DivUserListContainer')]")
                    )
                )
            except TimeoutException:
                return "No se encontro el modal de seguidores"

            # 6. SCRAPING CON SCROLL
            seguidores_encontrados = {}
            fecha_actual = datetime.now().replace(microsecond=0)
            intentos_sin_cambio = 0
            max_intentos = max(8, min(30, total_seg // 50)) if total_seg else 10

            def extraer_visibles():
                try:
                    items = scroll_box.find_elements(
                        By.XPATH, ".//li[.//p[contains(@class,'PUniqueId')]]"
                    )
                    for item in items:
                        try:
                            username = item.find_element(
                                By.XPATH, ".//p[contains(@class,'PUniqueId')]"
                            ).text.strip()
                            try:
                                full_name = item.find_element(
                                    By.XPATH, ".//span[contains(@class,'SpanNickname')]"
                                ).text.strip()
                            except Exception:
                                full_name = ""
                            if username and username not in seguidores_encontrados:
                                seguidores_encontrados[username] = full_name
                        except StaleElementReferenceException:
                            continue
                        except Exception:
                            continue
                except Exception as e:
                    print(f"[{self.tk_user}] Error extrayendo visibles: {e}")

            extraer_visibles()
            print(f"[{self.tk_user}] Inicio: {len(seguidores_encontrados)} visibles")

            while intentos_sin_cambio < max_intentos:
                antes = len(seguidores_encontrados)
                self._hacer_scroll(driver, scroll_box, veces=5, pausa=1.5)
                time.sleep(3)
                extraer_visibles()
                ahora = len(seguidores_encontrados)

                if ahora > antes:
                    intentos_sin_cambio = 0
                    print(f"[{self.tk_user}] {ahora} capturados (+{ahora - antes})")
                else:
                    intentos_sin_cambio += 1
                    print(f"[{self.tk_user}] Sin cambios ({intentos_sin_cambio}/{max_intentos})")

                if total_seg and ahora >= total_seg:
                    print(f"[{self.tk_user}] Objetivo alcanzado ({total_seg})")
                    break

            print(f"[{self.tk_user}] Captura final: {len(seguidores_encontrados)}")

            # 7. COMPARAR CON SNAPSHOT EN BD
            seguidores_hoy = {u: fn for u, fn in seguidores_encontrados.items() if u and len(u) > 1}
            snapshot_mysql = self._obtener_snapshot_actual(conn)
            seguidores_mysql = set(snapshot_mysql.keys())

            if not seguidores_mysql:
                todos = [
                    {"username": u, "full_name": fn, "scraped_at": fecha_actual}
                    for u, fn in seguidores_hoy.items()
                ]
                self._insertar_en_snapshot(conn, todos)
                return f"Primera ejecucion completada. {len(todos)} seguidores guardados."

            usernames_nuevos = set(seguidores_hoy.keys()) - seguidores_mysql
            if usernames_nuevos:
                nuevos = [
                    {"username": u, "full_name": seguidores_hoy[u], "scraped_at": fecha_actual}
                    for u in usernames_nuevos
                ]
                self._insertar_en_snapshot(conn, nuevos)
                en_lost = self._obtener_usuarios_en_lost(conn, usernames_nuevos)
                if en_lost:
                    self._eliminar_de_lost(conn, en_lost)

            usernames_perdidos = seguidores_mysql - set(seguidores_hoy.keys())
            if usernames_perdidos:
                self._eliminar_de_snapshot(conn, usernames_perdidos)
                perdidos = [
                    {
                        "username": u,
                        "full_name": snapshot_mysql.get(u, ""),
                        "fecha_perdida": fecha_actual
                    }
                    for u in usernames_perdidos
                ]
                self._insertar_en_lost(conn, perdidos)

            return (
                f"Scraping TikTok completado. "
                f"Encontrados: {len(seguidores_hoy)}. "
                f"Nuevos: {len(usernames_nuevos)}. "
                f"Perdidos: {len(usernames_perdidos)}."
            )

        except Exception as e:
            return f"Error general durante el scraping: {str(e)}"
        finally:
            driver.quit()
            conn.close()