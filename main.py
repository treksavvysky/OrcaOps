from fastapi import FastAPI
from orcaops.api import router as orcaops_router

app = FastAPI(
    title="OrcaOps API",
    description="A FastAPI application to manage Docker containers and sandbox templates.",
    version="1.0.0",
)

app.include_router(orcaops_router, prefix="/orcaops", tags=["orcaops"])

@app.get("/", summary="Root endpoint")
def read_root():
    """
    Root endpoint of the OrcaOps API.
    """
    return {"message": "Welcome to OrcaOps API"}
