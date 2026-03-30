from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import auth, stats, scraper, settings, autosync

# Crear tablas si no existen en la bd
Base.metadata.create_all(bind=engine)

app = FastAPI(title="RRSS Analytics Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Cambiar por dominio de frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#Registro de endpoints
app.include_router(auth.router)
app.include_router(scraper.router)
app.include_router(stats.router)
app.include_router(settings.router)
app.include_router(autosync.router)


@app.get("/")
def root():
    return {"status": "ok", "message": "Backend Operativo"}