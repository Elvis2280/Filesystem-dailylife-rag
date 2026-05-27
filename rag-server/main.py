import hashlib

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uuid import uuid4
from pathlib import Path
import shutil
import logging
import os

# Orchestration
from orchestration.pipeline_router import route_pipeline
from orchestration.workflow_manager import start_ingestion_workflow
from orchestration.pipeline_status import update_pipeline_status
from orchestration.websocket_events import publish_event

# Search
from search.hybrid_search import hybrid_search

# Shared
# from shared.config import settings


# =========================================================
# Logging
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# FastAPI App
# =========================================================

app = FastAPI(
    title="RAG Server",
    version="1.0.0",
    description="Distributed RAG orchestration server"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# Directories
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


# =========================================================
# Request Models
# =========================================================

class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class PipelineStatusRequest(BaseModel):
    job_id: str


# =========================================================
# Health Check
# =========================================================

@app.get("/")
def root():
    return {
        "message": "RAG Server Running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


# =========================================================
# Upload Endpoint
# =========================================================

@app.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):

    try:

        # -------------------------------------------------
        # Create Job ID
        # -------------------------------------------------

        job_id = str(uuid4())

        logger.info(f"New upload request received: {file.filename}")


        # -------------------------------------------------
        # Save Uploaded File
        # -------------------------------------------------

        file_extension = Path(file.filename).suffix.lower()

        stored_file_name = f"{job_id}{file_extension}"

        file_path = UPLOAD_DIR / stored_file_name

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        await file.seek(0) # Reset file pointer to read from the beginning
        file_bytes = await file.read()
        file_hash = hashlib.md5(file_bytes).hexdigest() 
        
        # Determine the page number (Defaulting to 1 or 0 depending on your pipeline)
        page_number = 1

        logger.info(f"File stored at: {file_path}")


        # -------------------------------------------------
        # Update Pipeline Status
        # -------------------------------------------------

        update_pipeline_status(
            job_id=job_id,
            status="UPLOADED"
        )


        # -------------------------------------------------
        # Publish WebSocket Event
        # -------------------------------------------------

        publish_event(
            job_id=job_id,
            event="UPLOAD_COMPLETE",
            data={
                "filename": file.filename
            }
        )


        # -------------------------------------------------
        # Route Pipeline
        # -------------------------------------------------

        pipeline_name = route_pipeline(file_path)

        logger.info(f"Pipeline selected: {pipeline_name}")


        # -------------------------------------------------
        # Start Workflow
        # -------------------------------------------------

        # background_tasks.add_task(
        #     start_ingestion_workflow,
        #     str(file_path),
        # )

        background_tasks.add_task(
            start_ingestion_workflow, 
            file_path=file_path,
            source_file=file.filename, 
            file_hash=file_hash,  
            page_number=page_number        
        )


        # -------------------------------------------------
        # Return Immediate Response
        # -------------------------------------------------

        return JSONResponse(
            status_code=202,
            content={
                "message": "Processing started",
                "job_id": job_id,
                "pipeline": pipeline_name.__name__
            }
        )


    except Exception as e:

        logger.exception("Upload failed")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================================================
# Query Endpoint
# =========================================================

@app.post("/query")
def query_documents(request: QueryRequest):

    try:

        logger.info(f"Incoming query: {request.question}")


        # -------------------------------------------------
        # Run Hybrid Search
        # -------------------------------------------------

        results = hybrid_search(
            query=request.question,
            top_k=request.top_k
        )


        # -------------------------------------------------
        # Build Context
        # -------------------------------------------------

        context_chunks = []

        for item in results:
            context_chunks.append(item["text"])

        context = "\n\n".join(context_chunks)


        # -------------------------------------------------
        # Placeholder LLM Response
        # -------------------------------------------------

        # Later this should call:
        # services.llm_service.generate_answer()

        answer = f"Generated answer using context:\n{context[:500]}"


        return {
            "question": request.question,
            "answer": answer,
            "retrieved_chunks": results
        }


    except Exception as e:

        logger.exception("Query failed")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================================================
# Pipeline Status Endpoint
# =========================================================

@app.get("/pipeline/status/{job_id}")
def get_pipeline_status(job_id: str):

    try:

        # Placeholder
        # Replace with actual implementation

        return {
            "job_id": job_id,
            "status": "PROCESSING"
        }


    except Exception as e:

        logger.exception("Status fetch failed")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================================================
# Delete Uploaded File
# =========================================================

@app.delete("/documents/{job_id}")
def delete_document(job_id: str):

    try:

        deleted = False

        for file in os.listdir(UPLOAD_DIR):

            if file.startswith(job_id):

                os.remove(UPLOAD_DIR / file)

                deleted = True

                logger.info(f"Deleted file for job: {job_id}")


        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )


        return {
            "message": "Document deleted",
            "job_id": job_id
        }


    except HTTPException:
        raise

    except Exception as e:

        logger.exception("Delete failed")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================================================
# Startup Event
# =========================================================

@app.on_event("startup")
def startup_event():

    logger.info("RAG Server Starting...")


# =========================================================
# Shutdown Event
# =========================================================

@app.on_event("shutdown")
def shutdown_event():

    logger.info("RAG Server Shutting Down...")


# =========================================================
# Run Server
# =========================================================

# Start using:
# uvicorn main:app --reload

