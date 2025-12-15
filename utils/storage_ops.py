from google.cloud import storage
from google.auth import default
from google.auth.transport.requests import Request
from google.auth import impersonated_credentials
import datetime
import os

BUCKET = os.getenv("INSPECTION_BUCKET")

VALID_ROLES = ["U", "P", "T"]
VALID_REMARKS = ["good", "replace"]

def generate_signed_url(request_id, role, remark, wo_id):
    role = role.upper()
    remark = remark.lower()

    if role not in VALID_ROLES:
        raise ValueError("Invalid role")

    if remark not in VALID_REMARKS:
        raise ValueError("Invalid remark")

    folder = f"{role}-{remark}".upper()
    file_path = f"{request_id}/{folder}/{wo_id}.jpg"

    # 🔐 Get default Cloud Run credentials
    source_credentials, project = default()
    source_credentials.refresh(Request())

    # 🔐 Impersonate SAME service account (this gives signing ability)
    target_credentials = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=source_credentials.service_account_email,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
        lifetime=300,
    )

    storage_client = storage.Client(credentials=target_credentials)
    bucket = storage_client.bucket(BUCKET)
    blob = bucket.blob(file_path)

    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=15),
        method="PUT",
        content_type="application/octet-stream"
    )

    return url
