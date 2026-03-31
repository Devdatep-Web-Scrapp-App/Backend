import json
from datetime import datetime
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, BadPassword, TwoFactorRequired, ChallengeRequired
from mysql.connector.pooling import MySQLConnectionPool
from app.config import settings


class InstagramScraperService:

    def __init__(self, app_user_id: int, ig_username: str, ig_password: str = None):
        self.app_user_id    = app_user_id
        self.ig_user        = ig_username
        self.ig_password    = ig_password
        self.db_batch_size  = 500
        self.table_snapshot = 'app_ig_followers_snapshot'
        self.table_lost     = 'app_ig_followers_lost'
        self.pool           = None
        self._init_pool(f'ig_pool_{self.app_user_id}')

    # ------------------------------------------------------------------ #
    #  Pool MySQL                                                         #
    # ------------------------------------------------------------------ #

    def _init_pool(self, pool_name: str):
        try:
            self.pool = MySQLConnectionPool(
                pool_name=pool_name,
                pool_size=2,
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                database=settings.DB_NAME
            )
        except Exception as e:
            print(f'Error creando pool MySQL ({pool_name}): {e}')

    def _conectar_mysql(self):
        if not self.pool:
            raise RuntimeError("Pool MySQL no inicializado")
        return self.pool.get_connection()

    @staticmethod
    def _chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    # ------------------------------------------------------------------ #
    #  Sesión en BD                                                       #
    # ------------------------------------------------------------------ #

    def _get_session_from_db(self, conn) -> str | None:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT ig_session FROM app_users WHERE id = %s",
                (self.app_user_id,)
            )
            row = cursor.fetchone()
            return row['ig_session'] if row and row['ig_session'] else None

    def _save_session_to_db(self, conn, session_json: str):
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE app_users SET ig_session = %s WHERE id = %s",
                (session_json, self.app_user_id)
            )
            conn.commit()

    def _clear_session_from_db(self, conn):
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE app_users SET ig_session = NULL WHERE id = %s",
                (self.app_user_id,)
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    #  Consultas BD                                                       #
    # ------------------------------------------------------------------ #

    def _obtener_snapshot_actual(self, conn) -> dict:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                f"SELECT username, full_name FROM {self.table_snapshot} WHERE app_user_id = %s",
                (self.app_user_id,)
            )
            return {r['username']: r['full_name'] for r in cursor.fetchall()}

    def _obtener_usuarios_en_lost(self, conn, usernames: set) -> set:
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
                cursor.executemany(query, [
                    (self.app_user_id, s['username'], s['full_name'], s['scraped_at'])
                    for s in batch
                ])
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
                cursor.executemany(query, [
                    (self.app_user_id, p['username'], p['full_name'], p['fecha_perdida'])
                    for p in batch
                ])
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
    #  Instagrapi - Cliente                                               #
    # ------------------------------------------------------------------ #

    def _build_client(self, conn) -> Client:
        cl = Client()
        cl.delay_range = [1, 3]

        session_json = self._get_session_from_db(conn)
        if session_json:
            try:
                cl.set_settings(json.loads(session_json))
                cl.login(self.ig_user, self.ig_password or "")
                cl.get_timeline_feed()
                print(f"[{self.ig_user}] Sesion reutilizada correctamente.")
                # Actualizar sesion por si instagrapi la refresco internamente
                self._save_session_to_db(conn, json.dumps(cl.get_settings()))
                return cl
            except LoginRequired:
                print(f"[{self.ig_user}] Sesion expirada, relogueando...")
                self._clear_session_from_db(conn)
                cl = Client()
                cl.delay_range = [1, 3]

        if not self.ig_password:
            raise ValueError("Se requiere contraseña para el primer login.")

        cl.login(self.ig_user, self.ig_password)
        self._save_session_to_db(conn, json.dumps(cl.get_settings()))
        print(f"[{self.ig_user}] Login exitoso, sesion guardada en BD.")
        return cl

    # ------------------------------------------------------------------ #
    #  Setup de sesión                                                    #
    # ------------------------------------------------------------------ #

    def setup_session(self):
        conn = self._conectar_mysql()
        try:
            self._build_client(conn)
            return "Sesion de Instagram configurada correctamente."
        except BadPassword:
            raise ValueError("Contraseña incorrecta.")
        except TwoFactorRequired:
            raise ValueError("La cuenta tiene verificación en dos pasos. Desactívala temporalmente.")
        except ChallengeRequired:
            raise ValueError("Instagram requiere verificación adicional. Aprueba el acceso desde la app de Instagram y vuelve a intentarlo.")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Error durante el setup: {str(e)}")
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    #  Sincronización BD                                                  #
    # ------------------------------------------------------------------ #

    def _sincronizar_bd(self, conn, seguidores_encontrados: dict) -> str:
        fecha_actual     = datetime.now().replace(microsecond=0)
        seguidores_hoy   = {u: fn for u, fn in seguidores_encontrados.items() if u and len(u) > 1}
        snapshot_mysql   = self._obtener_snapshot_actual(conn)
        seguidores_mysql = set(snapshot_mysql.keys())

        if not seguidores_mysql:
            self._insertar_en_snapshot(conn, [
                {"username": u, "full_name": fn, "scraped_at": fecha_actual}
                for u, fn in seguidores_hoy.items()
            ])
            return f"Primera ejecucion completada. {len(seguidores_hoy)} seguidores guardados."

        usernames_nuevos = set(seguidores_hoy.keys()) - seguidores_mysql
        if usernames_nuevos:
            self._insertar_en_snapshot(conn, [
                {"username": u, "full_name": seguidores_hoy[u], "scraped_at": fecha_actual}
                for u in usernames_nuevos
            ])
            en_lost = self._obtener_usuarios_en_lost(conn, usernames_nuevos)
            if en_lost:
                self._eliminar_de_lost(conn, en_lost)

        usernames_perdidos = seguidores_mysql - set(seguidores_hoy.keys())
        if usernames_perdidos:
            self._eliminar_de_snapshot(conn, usernames_perdidos)
            self._insertar_en_lost(conn, [
                {"username": u, "full_name": snapshot_mysql.get(u, ""), "fecha_perdida": fecha_actual}
                for u in usernames_perdidos
            ])

        return (
            f"Scraping completado. "
            f"Encontrados: {len(seguidores_hoy)}. "
            f"Nuevos: {len(usernames_nuevos)}. "
            f"Perdidos: {len(usernames_perdidos)}."
        )

    # ------------------------------------------------------------------ #
    #  Extracción principal                                               #
    # ------------------------------------------------------------------ #

    def run_extraction(self):
        conn = self._conectar_mysql()
        if not conn:
            return "Database connection failed"

        try:
            cl = self._build_client(conn)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error de login: {str(e)}"

        try:
            user_id = cl.user_id_from_username(self.ig_user)
            print(f"[{self.ig_user}] User ID: {user_id}")

            print(f"[{self.ig_user}] Obteniendo seguidores...")
            followers_raw = cl.user_followers(user_id, amount=0)

            seguidores_encontrados = {
                user.username: user.full_name
                for user in followers_raw.values()
            }
            print(f"[{self.ig_user}] Total capturados: {len(seguidores_encontrados)}")

            return self._sincronizar_bd(conn, seguidores_encontrados)

        except LoginRequired:
            self._clear_session_from_db(conn)
            return "Sesion expirada durante el scraping. Vuelve a ejecutar setup-instagram."
        except Exception as e:
            return f"Error durante el scraping: {str(e)}"
        finally:
            conn.close()