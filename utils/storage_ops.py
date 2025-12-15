from google.cloud import storage
import datetime
from datetime import timedelta
import os

storage_client = storage.Client()
BUCKET = os.getenv("INSPECTION_BUCKET")

VALID_ROLES = ["U", "P", "T"]
VALID_REMARKS = ["good", "replace"]

def generate_signed_url(request_id, role, remark, wo_id):
    bucket_name = os.environ["INSPECTION_BUCKET"]

    filename = f"{request_id}/{wo_id}/{role}_{remark}.jpg"

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(filename)

    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=15),
        method="PUT",
        content_type="application/octet-stream",
        service_account_email=client._credentials.service_account_email,
        access_token=client._credentials.token,
    )

    return url
