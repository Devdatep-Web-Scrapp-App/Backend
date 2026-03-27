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
from webdriver_manager.core.os_manager import ChromeType
from mysql.connector.pooling import MySQLConnectionPool
from app.config import settings


class InstagramScraperService:
    def __init__(self, app_user_id: int, ig_username: str, ig_password: str):
        self.app_user_id  = app_user_id
        self.ig_user      = ig_username
        self.ig_password  = ig_password
        self.db_batch_size = 500
        self.table_snapshot = 'app_ig_followers_snapshot'
        self.table_lost     = 'app_ig_followers_lost'
        self.pool = None

        self.session_dir = os.path.join(
            os.getcwd(), "chrome_sessions", f"user_{self.app_user_id}"
        )
        os.makedirs(self.session_dir, exist_ok=True)
        self._init_pool()

    # Pool MySQL

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
        if not self.pool:
            self._init_pool()
        return self.pool.get_connection() if self.pool else None

    def _chunks(self, lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def _tiene_sesion_guardada(self):
        cookies_file = os.path.join(self.session_dir, "Default", "Cookies")
        network_file = os.path.join(self.session_dir, "Default", "Network", "Cookies")
        if os.path.exists(network_file) and os.path.getsize(network_file) > 10_000:
            return True
        if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 10_000:
            return True
        return False

    def _hacer_scroll(self, driver, scroll_box, veces=3, pausa=0.5):
        for _ in range(veces):
            try:
                driver.execute_script("""
                    var box   = arguments[0];
                    var items = box.querySelectorAll('div, li');
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

    def _esperar_carga(self, driver, timeout=8):
        try:
            WebDriverWait(driver, timeout).until(
                EC.invisibility_of_element_located(
                    (By.XPATH, "//div[@role='progressbar']")
                )
            )
        except Exception:
            pass

    def _obtener_numero_seguidores(self, driver):
        try:
            time.sleep(2)
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]/span")
                )
            )
            txt = el.get_attribute('title') or el.text
            return int(''.join(filter(str.isdigit, txt)))
        except Exception:
            return None

    # Consultas BD

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

    # Selenium

    def _build_driver(self):
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={self.session_dir}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--headless=new")

        # webdriver-manager descarga el chromedriver correcto automaticamente
        # Forzar descarga del driver win64 y apuntar al .exe correcto
        import glob
        os.environ["WDM_ARCH"] = "64"
        driver_path = ChromeDriverManager().install()
        # webdriver-manager a veces apunta a THIRD_PARTY_NOTICES en vez del exe
        # buscamos el chromedriver.exe real en la misma carpeta
        if not driver_path.endswith(".exe"):
            exe_candidates = glob.glob(
                os.path.join(os.path.dirname(driver_path), "chromedriver*.exe")
            )
            if exe_candidates:
                driver_path = exe_candidates[0]
        service = Service(driver_path)
        return webdriver.Chrome(service=service, options=chrome_options)

    # ------------------------------------------------------------------ #
    #  Extraccion principal                                                #
    # ------------------------------------------------------------------ #

    def setup_session(self):
        """
        Abre Chrome VISIBLE para que el usuario haga login manual una sola vez.
        Guarda las cookies en disco. Despues de esto run_extraction corre headless.
        """
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={self.session_dir}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--start-maximized")

        import glob
        os.environ["WDM_ARCH"] = "64"
        driver_path = ChromeDriverManager().install()
        if not driver_path.endswith(".exe"):
            exe_candidates = glob.glob(
                os.path.join(os.path.dirname(driver_path), "chromedriver*.exe")
            )
            if exe_candidates:
                driver_path = exe_candidates[0]
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.get(f"https://www.instagram.com/{self.ig_user}/")
        print(f"[{self.ig_user}] Abre el navegador, inicia sesion manualmente y cierra la ventana.")
        # Esperar hasta 5 minutos a que el usuario haga login y aparezca el link de followers
        try:
            WebDriverWait(driver, 300).until(
                EC.presence_of_element_located(
                    (By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]")
                )
            )
            print(f"[{self.ig_user}] Sesion guardada correctamente.")
            time.sleep(3)
        except TimeoutException:
            print(f"[{self.ig_user}] Tiempo agotado esperando login manual.")
        finally:
            driver.quit()

    def run_extraction(self):
        conn = self._conectar_mysql()
        if not conn:
            return "Database connection failed"

        # Si no hay sesion guardada, no intentar login automatico headless
        # El usuario debe llamar primero a setup_session()
        if not self._tiene_sesion_guardada():
            return "No hay sesion de Instagram guardada. Llama primero a setup_session() o usa el endpoint /scraper/setup-instagram."

        driver = self._build_driver()

        try:
            # 1. NAVEGAR AL PERFIL
            driver.get(f"https://www.instagram.com/{self.ig_user}/")
            print(f"[{self.ig_user}] Accediendo al perfil...")
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # 2. VERIFICAR SESION
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]")
                    )
                )
                print(f"[{self.ig_user}] Sesion activa, continuando...")
            except TimeoutException:
                return "La sesion de Instagram expiro. Vuelve a ejecutar setup_session()."

            # 3. TOTAL DE SEGUIDORES
            total_seg = self._obtener_numero_seguidores(driver) or 0
            print(f"[{self.ig_user}] Total segun perfil: {total_seg or 'desconocido'}")

            # 4. ABRIR MODAL DE SEGUIDORES
            try:
                btn = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, f"//a[contains(@href, '/{self.ig_user}/followers/')]")
                    )
                )
                btn.click()
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
                )
            except TimeoutException:
                return "No se pudo abrir la lista de seguidores"

            # 5. UBICAR CAJA DE SCROLL
            try:
                dialog = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
                )
                # Instagram cambia los estilos frecuentemente, probamos varios selectores
                scroll_box = None
                scroll_selectors = [
                    ".//div[contains(@style, 'overflow: hidden auto')]",
                    ".//div[contains(@style, 'overflow-y: auto')]",
                    ".//div[contains(@style, 'overflow: auto')]",
                    ".//div[@role='dialog']//ul",
                    ".//div[@role='dialog']//div[last()]",
                ]
                for selector in scroll_selectors:
                    try:
                        scroll_box = dialog.find_element(By.XPATH, selector)
                        print(f"[{self.ig_user}] Modal encontrado con selector: {selector}")
                        break
                    except Exception:
                        continue
                if scroll_box is None:
                    # Fallback: usar el dialog completo como scroll box
                    scroll_box = dialog
                    print(f"[{self.ig_user}] Usando dialog completo como scroll box.")
            except TimeoutException:
                return "No se encontro el modal de scroll"

            # 6. SCRAPING CON SCROLL
            seguidores_encontrados = {}
            fecha_actual           = datetime.now().replace(microsecond=0)
            intentos_sin_cambio    = 0
            max_intentos = max(8, min(30, total_seg // 50)) if total_seg else 10

            def extraer_visibles():
                try:
                    elementos = scroll_box.find_elements(
                        By.XPATH, ".//div[contains(@class, 'x1qnrgzn')]"
                    )
                    for el in elementos:
                        try:
                            username = el.find_element(
                                By.XPATH, ".//span[contains(@class, '_ap3a')]"
                            ).text.strip()
                            try:
                                full_name = el.find_element(
                                    By.XPATH,
                                    ".//span[contains(@class, 'x1lliihq') "
                                    "and contains(@class, 'x193iq5w')]"
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
                    print(f"[{self.ig_user}] Error extrayendo visibles: {e}")

            extraer_visibles()
            print(f"[{self.ig_user}] Inicio: {len(seguidores_encontrados)} visibles")

            while intentos_sin_cambio < max_intentos:
                antes = len(seguidores_encontrados)
                self._hacer_scroll(driver, scroll_box, veces=3, pausa=0.5)
                self._esperar_carga(driver)
                extraer_visibles()
                ahora = len(seguidores_encontrados)

                if ahora > antes:
                    intentos_sin_cambio = 0
                    print(f"[{self.ig_user}] {ahora} capturados (+{ahora - antes})")
                else:
                    intentos_sin_cambio += 1

                if total_seg and ahora >= total_seg:
                    break

            print(f"[{self.ig_user}] Captura final: {len(seguidores_encontrados)}")

            # 7. COMPARAR CON SNAPSHOT EN BD
            seguidores_hoy   = {u: fn for u, fn in seguidores_encontrados.items() if u and len(u) > 1}
            snapshot_mysql   = self._obtener_snapshot_actual(conn)
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
                f"Scraping completado. "
                f"Encontrados: {len(seguidores_hoy)}. "
                f"Nuevos: {len(usernames_nuevos)}. "
                f"Perdidos: {len(usernames_perdidos)}."
            )

        except Exception as e:
            return f"Error general durante el scraping: {str(e)}"
        finally:
            driver.quit()
            conn.close()