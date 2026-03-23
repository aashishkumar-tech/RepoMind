"""
step1/lambda_handler.py — AWS Lambda Entry Point (Mangum Adapter)

HOW IT WORKS:
─────────────
AWS Lambda doesn't speak ASGI (FastAPI's protocol).
Mangum is the bridge:

    API Gateway Event → Mangum → FastAPI → Your Code → Response → Mangum → API Gateway

This file is what Lambda calls. It wraps the FastAPI app.

WHY SEPARATE FILE:
    - webhook_handler.py contains the FastAPI app (testable locally with uvicorn)
    - lambda_handler.py wraps it for Lambda (used only in deployment)
    - You can run locally: uvicorn step1.webhook_handler:app --reload
    - Or deploy to Lambda: handler = step1.lambda_handler.handler

SAM TEMPLATE REFERENCE:
    In template.yaml, the Handler is: step1.lambda_handler.handler
"""

from mangum import Mangum
from step1.webhook_handler import app

# Mangum wraps FastAPI for Lambda
# This is the function Lambda invokes
handler = Mangum(app, lifespan="off")
