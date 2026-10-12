"""Local development scaffold only; application routes await the go/no-go review."""

from fastapi import FastAPI

app = FastAPI(
    title="StreamSense development scaffold", docs_url=None, redoc_url=None, openapi_url=None
)


@app.get("/health")
def health() -> dict[str, str]:
    """Report process liveness only, without claiming database or GPU readiness."""
    return {"status": "ok", "stage": "development-readiness"}
