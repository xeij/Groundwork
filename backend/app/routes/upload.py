from typing import Literal

from fastapi import APIRouter

from ..models import UploadResponse
from ..services.storage import generate_upload_url

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
def upload(documentType: Literal["lease", "filing"] = "lease"):
    presigned_url, s3_key = generate_upload_url(documentType)
    return UploadResponse(presignedUrl=presigned_url, s3Key=s3_key)
