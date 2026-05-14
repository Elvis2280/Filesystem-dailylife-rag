from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Memory RAG", version="1.0.0")


@app.get("/")
def root():
    return JSONResponse(content={"message": "Hello World", "status": "ok"})


@app.get("/health")
def health():
    return JSONResponse(content={"status": "healthy"})