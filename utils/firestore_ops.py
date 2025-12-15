
from google.cloud import firestore
import uuid
import datetime
import os

from utils.pubsub_ops import publish_request_event,publish_po_event

db = firestore.Client()
REQUEST_COLL = os.getenv("REQUESTS_COLLECTION", "requests")
WORKORDERS_COLL = os.getenv("WORKORDERS_COLLECTION", "work_orders")

TECH_ROLES = [
    {"role": "U", "name": "Unit"},
    {"role": "P", "name": "Pole"},
    {"role": "T", "name": "Transformer"},
]

def _now_ts():
    return datetime.datetime.now(datetime.timezone.utc)

def create_work_orders(request_id: str, request_type: str, created_by: str = None):
    """
    Create 3 work_orders documents (U,P,T) for the request and return list of woIds.
    Each work order will include request_type copied from request document.
    """
    wo_ids = []
    batch = db.batch()
    for r in TECH_ROLES:
        wo_id = f"WO-{uuid.uuid4().hex[:12]}"
        doc_ref = db.collection(WORKORDERS_COLL).document(wo_id)
        payload = {
            "woId": wo_id,
            "requestId": request_id,
            "technician_role": r["role"],
            "technician_role_name": r["name"],
            "request_type": request_type,
            "status": "PENDING",
            "assigned_to": None,
            "inspection_file": None,
            "remark": None,
            "remark_text": None,
            "po_created": False,
            "po_id": None,
            "created_at": _now_ts(),
            "updated_at": _now_ts(),
        }
        batch.set(doc_ref, payload)
        wo_ids.append(wo_id)
    # commit the batch to create all work orders atomically
    batch.commit()
    return wo_ids

def create_request(data: dict) -> dict:
    """
    Create a request document and 3 work orders.
    Expected input data keys: customer_name, phone_number, location, request_type, description (optional)
    Returns the created request document info.
    """
    try:
        # validate minimal fields
        customer_name = data.get("customer_name") or data.get("name")
        phone = data.get("phone_number") or data.get("phone")
        location = data.get("location")
        request_type = data.get("request_type") or data.get("type", "UNKNOWN")
        description = data.get("description", "")

        if not customer_name or not phone or not location:
            return {"error": "customer_name, phone_number and location are required"}

        request_id = f"SN-{uuid.uuid4().hex[:10]}"
        request_doc = db.collection(REQUEST_COLL).document(request_id)
        now = _now_ts()
        request_payload = {
            "requestId": request_id,
            "customer_name": customer_name,
            "phone_number": phone,
            "location": location,
            "request_type": request_type,
            "description": description,
            "status": "CRT",  # created
            "workorder_ids": [],
            "created_at": now,
            "updated_at": now,
        }

        # create request doc
        request_doc.set(request_payload)

        # create work orders and attach ids to request
        wo_ids = create_work_orders(request_id, request_type)
        request_doc.update({"workorder_ids": wo_ids, "updated_at": _now_ts()})

        # publish request event to Pub/Sub for analytics (best-effort)
        event_payload = {
            "event": "REQUEST_CREATED",
            "requestId": request_id,
            "customer_name": customer_name,
            "phone_number": phone,
            "location": location,
            "request_type": request_type,
            "workorder_ids": wo_ids,
            "created_at": now.isoformat() + "Z",
            "source": "cloudrun-backend"
        }
        publish_request_event(event_payload)

        # return created object
        result = {"requestId": request_id, **request_payload, "workorder_ids": wo_ids}
        return result

    except Exception as e:
        print("create_request error:", e)
        return {"error": str(e)}
def update_work_order_status(wo_id: str, status: str) -> dict:
    """
    Update a work order status (IN-PROGRESS, GOOD, REPLACE),
    and also update the parent request status accordingly.
    """
    try:
        wo_ref = db.collection(WORKORDERS_COLL).document(wo_id)
        wo_doc = wo_ref.get()

        if not wo_doc.exists:
            return {"error": f"Work order {wo_id} not found"}

        wo_data = wo_doc.to_dict()
        request_id = wo_data["requestId"]

        # 1️⃣ Update the work order itself
        wo_ref.update({
            "status": status,
            "updated_at": _now_ts(),
        })

        req_ref = db.collection(REQUEST_COLL).document(request_id)

        # 2️⃣ If technician just started
        if status == "IN-PROGRESS":
            req_ref.update({
                "status": "IN-PROGRESS",
                "updated_at": _now_ts(),
            })

        # 3️⃣ If technician submitted GOOD or REPLACE
        elif status in ["GOOD", "REPLACE"]:
            req_doc = req_ref.get().to_dict()
            wo_ids = req_doc.get("workorder_ids", [])

            completed = 0
            replace_found = False

            for wid in wo_ids:
                w_doc = db.collection(WORKORDERS_COLL).document(wid).get()
                if not w_doc.exists:
                    continue

                w = w_doc.to_dict()
                wo_status = w.get("status")

                if wo_status in ["GOOD", "REPLACE"]:
                    completed += 1

                if wo_status == "REPLACE":
                    replace_found = True

            # ✅ All 3 technicians finished inspection
            if completed == 3:
                if replace_found:
                    req_ref.update({
                        "status": "INSPECTION_COMPLETED",
                        "replacement_required": True,
                        "total_replacements": sum(
                            1 for wid in wo_ids
                            if db.collection(WORKORDERS_COLL)
                            .document(wid)
                            .get()
                            .to_dict()
                            .get("status") == "REPLACE"
                        ),
                        "purchase_orders_created": 0,
                        "updated_at": _now_ts(),
                    })
                else:
                    # ✅ ALL GOOD → COMPLETED
                    req_ref.update({
                        "status": "COMPLETED",
                        "replacement_required": False,
                        "updated_at": _now_ts(),
                    })



        return {
            "message": f"Work order {wo_id} updated successfully",
            "status": status
        }

    except Exception as e:
        print("update_work_order_status error:", e)
        return {"error": str(e)}

def create_purchase_order(data: dict) -> dict:
    """
    Create a purchase order ONLY after inspection is completed
    and replacement is required.
    """
    try:
        request_id = data.get("requestId")
        wo_id = data.get("woId")
        item = data.get("item_name")
        qty = data.get("quantity")
        price = data.get("price")

        if not request_id or not wo_id or not item:
            return {"error": "requestId, woId and item_name are required"}

        # 🔍 Fetch request
        req_ref = db.collection(REQUEST_COLL).document(request_id)
        req_doc = req_ref.get()

        if not req_doc.exists:
            return {"error": "Request not found"}

        req_data = req_doc.to_dict()

        # ✅ Allow PO only after inspection completed
        if req_data.get("status") != "INSPECTION_COMPLETED":
            return {"error": "Inspection not completed yet"}

        # ✅ Allow PO only if replacement is required
        if not req_data.get("replacement_required", False):
            return {"error": "Replacement not required for this request"}

        # 🔍 Fetch work order
        wo_ref = db.collection(WORKORDERS_COLL).document(wo_id)
        wo_doc = wo_ref.get()

        if not wo_doc.exists:
            return {"error": "Work order not found"}

        wo_data = wo_doc.to_dict()

        if wo_data.get("po_created"):
            return {"error": "Purchase order already created for this work order"}

        po_id = f"PO-{uuid.uuid4().hex[:12]}"
        now = _now_ts()

        # 1️⃣ Create PO document
        po_payload = {
            "poId": po_id,
            "requestId": request_id,
            "woId": wo_id,
            "item_name": item,
            "quantity": qty,
            "price": price,
            "status": "CREATED",
            "created_at": now,
            "updated_at": now,
        }

        db.collection("purchase_orders").document(po_id).set(po_payload)

        # 2️⃣ Update work order
        wo_ref.update({
            "po_created": True,
            "po_id": po_id,
            "updated_at": now,
        })

        # 3️⃣ Update request → ORDERED (ONLY HERE ✅)
        # 3️⃣ Increment PO count
        req_ref = db.collection(REQUEST_COLL).document(request_id)

        req_ref.update({
            "purchase_orders_created": firestore.Increment(1),
            "updated_at": now,
        })

        # 4️⃣ Check if all POs are created
        req_doc = req_ref.get().to_dict()

        if req_doc.get("purchase_orders_created", 0) >= req_doc.get("total_replacements", 0):
            req_ref.update({
                "status": "ORDERED",
                "updated_at": now,
            })


        # 4️⃣ Publish PO event
        try:
            publish_po_event({
                "event": "PO_CREATED",
                "poId": po_id,
                "requestId": request_id,
                "woId": wo_id,
                "item_name": item,
                "quantity": qty,
                "price": price,
                "created_at": now.isoformat() + "Z",
            })
        except Exception as e:
            print("PO PubSub publish failed:", e)

        return {
            "message": "Purchase order created successfully",
            "poId": po_id
        }

    except Exception as e:
        print("create_purchase_order error:", e)
        return {"error": str(e)}
    
def get_work_orders_by_status(status: str):
    try:
        docs = (
            db.collection(WORKORDERS_COLL)
            .where("status", "==", status)
            .stream()
        )

        results = []
        for d in docs:
            data = d.to_dict()
            results.append(data)

        return results

    except Exception as e:
        print("get_work_orders_by_status error:", e)
        return []
