from google.cloud import storage
from google.auth import default
from google.auth.transport.requests import Request
from google.auth.iam import Signer
import datetime
import os

# Env
BUCKET = os.getenv("INSPECTION_BUCKET")

VALID_ROLES = ["U", "P", "T"]
VALID_REMARKS = ["good", "replace"]

# Create storage client
storage_client = storage.Client()

# Get default credentials + service account email
credentials, project = default()
credentials.refresh(Request())

service_account_email = credentials.service_account_email

# IAM Signer (THIS is the key difference)
signer = Signer(
    Request(),
    credentials,
    service_account_email
)

def generate_signed_url(request_id, role, remark, wo_id):
    role = role.upper()
    remark = remark.lower()

    if role not in VALID_ROLES:
        raise ValueError("Invalid role")

    if remark not in VALID_REMARKS:
        raise ValueError("Invalid remark")

    folder = f"{role}-{remark}".upper()
    file_path = f"{request_id}/{folder}/{wo_id}.jpg"

    bucket = storage_client.bucket(BUCKET)
    blob = bucket.blob(file_path)

    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=15),
        method="PUT",
        credentials=credentials,
        service_account_email=service_account_email,
        signer=signer,
        content_type="application/octet-stream"
    )

    return url
