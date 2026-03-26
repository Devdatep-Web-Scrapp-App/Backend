## Tecnologías Principales

- **Framework:** FastAPI (Python)
- **Base de Datos:** MySQL
- **Tareas asíncronas:** Celery + Redis
- **Scraping:** Selenium (Google Chrome Headless)
- **Despliegue local:** Docker & Docker Compose

---

## Resumen de Endpoints Principales

_Toda la documentación exacta (cuerpos JSON, tipos de datos y respuestas) se autogenera. Una vez levantes el proyecto, visita `http://localhost:8000/docs` para ver la interfaz de Swagger y probar los endpoints._

### Autenticación (`/auth`)

- `POST /auth/register`: Crea un nuevo usuario en la plataforma.
- `POST /auth/login`: Recibe email/password y devuelve el token JWT.
- `POST /auth/forgot-password`: Inicia la recuperación de contraseña.
- `POST /auth/reset-password`: Cambia la contraseña usando el token temporal.

### Configuración del Usuario (`/settings`)

- `PUT /settings/update-profile`: Actualiza datos básicos (ej. nombre completo).
- `PUT /settings/change-password`: Cambia la contraseña actual.
- `PUT /settings/connect-instagram`: Guarda las credenciales de IG del usuario para uso del bot.
- `PUT /settings/connect-tiktok`: Guarda las credenciales de TikTok del usuario para uso del bot.

### Ejecución del Scraper (`/scraper`)

- `POST /scraper/run-instagram`: Envía la tarea de extracción de IG a la cola de trabajo.
- `POST /scraper/run-tiktok`: Envía la tarea de extracción de TikTok a la cola de trabajo.

### Estadísticas y Métricas (`/stats`)

- `GET /stats/instagram/followers`: Devuelve la lista de seguidores activos actuales.
- `GET /stats/instagram/lost`: Devuelve la lista de usuarios que dejaron de seguir (unfollows) con su fecha.
- `GET /stats/tiktok/followers`: Devuelve la lista de seguidores activos actuales.
- `GET /stats/tiktok/lost`: Devuelve la lista de unfollows.
- `GET /stats/history`: Devuelve un resumen numérico (totales) de ambas redes para pintar en un Dashboard.

---

## Cómo levantar el entorno localmente (Frontend)

Si necesitas levantar el backend en tu máquina para probar la integración, no necesitas instalar Python ni bases de datos, solo **Docker**.

1. Instala [Docker Desktop](https://www.docker.com/products/docker-desktop).
2. Clona este repositorio y abre una terminal en la carpeta raíz (donde está el archivo `docker-compose.yml`).
3. Ejecuta el siguiente comando:
   ```bash
   docker-compose up --build
   ```
