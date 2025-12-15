from google.cloud import storage
import datetime
import os

storage_client = storage.Client()
BUCKET = os.getenv("INSPECTION_BUCKET")

VALID_ROLES = ["U", "P", "T"]
VALID_REMARKS = ["good", "replace"]

def generate_signed_url(request_id, role, remark, wo_id):
    """
    GCS Path:
    <requestId>/<ROLE>-<REMARK>/<WO_ID>.jpg
    """

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
        method="PUT"
    )

    return url
