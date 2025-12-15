from flask import Flask, request, jsonify
from google.cloud import firestore
from flask_cors import CORS

# Firestore business logic functions
from utils.firestore_ops import (
    create_request,
    update_work_order_status,
    create_purchase_order,
    get_work_orders_by_status
)

# GCS Signed URL utility
from utils.storage_ops import generate_signed_url

app = Flask(__name__)

CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)


db = firestore.Client()
REQUEST_COLL = "requests"

# ---------------------------------------------------------
# Helper to convert Firestore document to dict
# ---------------------------------------------------------
def request_to_dict(doc):
    d = doc.to_dict()
    d["id"] = doc.id
    return d


# ---------------------------------------------------------
# Test Route
# ---------------------------------------------------------
@app.get("/")
def home():
    return jsonify({"message": "Backend is running"}), 200


# ---------------------------------------------------------
# 1. CUSTOMER — Create Request
# ---------------------------------------------------------
@app.post("/api/requests")
def api_create_request():
    data = request.json
    response = create_request(data)
    return jsonify(response), 200


# ---------------------------------------------------------
# 2. TECHNICIAN — Mark Work Order as IN-PROGRESS
# ---------------------------------------------------------
@app.post("/api/work-orders/<wo_id>/inspect")
def api_inspect_work_order(wo_id):
    result = update_work_order_status(wo_id, "IN-PROGRESS")
    return jsonify(result), 200


# ---------------------------------------------------------
# 3. TECHNICIAN — Generate Signed URL for Upload
# ---------------------------------------------------------
@app.get("/api/upload-url")
def api_signed_url():
    request_id = request.args.get("requestId")
    role = request.args.get("role")
    remark = request.args.get("remark")
    wo_id = request.args.get("woId")

    if not all([request_id, role, remark, wo_id]):
        return jsonify({"error": "Missing parameters"}), 400

    url = generate_signed_url(request_id, role, remark, wo_id)
    return jsonify({"signed_url": url}), 200



# ---------------------------------------------------------
# 4. TECHNICIAN — Submit Final Remark
# ---------------------------------------------------------
@app.post("/api/work-orders/<wo_id>/submit")
def api_submit_work_order(wo_id):
    """
    Expected JSON:
    {
      "remark": "GOOD" or "REPLACE" 
    }
    """
    data = request.json
    remark = data.get("remark")

    if not remark:
        return jsonify({"error": "remark is required"}), 400

    result = update_work_order_status(wo_id, remark.upper())
    return jsonify(result), 200


# ---------------------------------------------------------
# 5. PURCHASE ORDER — Create PO
# ---------------------------------------------------------
@app.post("/api/purchase-orders")
def api_po_create():
    data = request.json
    response = create_purchase_order(data)
    return jsonify(response), 200
# ---------------------------------------------------------
# 5B. PURCHASE ORDER — List All POs
# ---------------------------------------------------------
@app.get("/api/purchase-orders")
def api_get_purchase_orders():
    try:
        docs = db.collection("purchase_orders").order_by(
            "created_at", direction=firestore.Query.DESCENDING
        ).stream()

        results = []
        for d in docs:
            results.append(d.to_dict())

        return jsonify({"purchase_orders": results}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------
# 6. LISTING APIs — Incoming Requests
# ---------------------------------------------------------
@app.get("/api/requests/incoming")
def api_incoming_requests():
    statuses = ["CRT", "PENDING", "IN-PROGRESS", "INSPECTION_COMPLETED"]
    docs = (
        db.collection(REQUEST_COLL)
        .where("status", "in", statuses)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    results = [request_to_dict(d) for d in docs]
    return jsonify({"incoming_requests": results}), 200


# ---------------------------------------------------------
# 7. LISTING — Completed Requests
# ---------------------------------------------------------
@app.get("/api/requests/completed")
def api_completed_requests():
    docs = (
        db.collection(REQUEST_COLL)
        .where("status", "==", "COMPLETED")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )

    results = []

    for d in docs:
        req = d.to_dict()
        request_id = req["requestId"]

        wo_docs = (
            db.collection("work_orders")
            .where("requestId", "==", request_id)
            .stream()
        )

        req["work_orders"] = [wo.to_dict() for wo in wo_docs]
        results.append(req)

    return jsonify({"completed_requests": results}), 200



# ---------------------------------------------------------
# 8. LISTING — Ordered Requests
# ---------------------------------------------------------
@app.get("/api/requests/ordered")
def api_ordered_requests():
    docs = (
        db.collection(REQUEST_COLL)
        .where("status", "==", "ORDERED")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )

    results = []

    for d in docs:
        req = d.to_dict()
        request_id = req["requestId"]

        # 🔹 Fetch work orders
        wo_docs = (
            db.collection("work_orders")
            .where("requestId", "==", request_id)
            .stream()
        )
        work_orders = [wo.to_dict() for wo in wo_docs]

        # 🔹 Fetch purchase orders
        po_docs = (
            db.collection("purchase_orders")
            .where("requestId", "==", request_id)
            .stream()
        )
        purchase_orders = [po.to_dict() for po in po_docs]

        results.append({
            **req,
            "work_orders": work_orders,
            "purchase_orders": purchase_orders
        })

    return jsonify({"ordered_requests": results}), 200



# ---------------------------------------------------------
# 9. SEARCH — Search Request by ID
# ---------------------------------------------------------
@app.get("/api/requests/search")
def api_search_request():
    req_id = request.args.get("requestId")

    if not req_id:
        return jsonify({"error": "requestId query param is required"}), 400

    doc_ref = db.collection(REQUEST_COLL).document(req_id)
    doc = doc_ref.get()

    if not doc.exists:
        return jsonify({"message": "Request not found"}), 404

    return jsonify({"request": request_to_dict(doc)}), 200

# ---------------------------------------------------------
# 10. LISTING — Work Orders by Status (Technician)
# ---------------------------------------------------------
@app.get("/api/work-orders")
def api_get_work_orders():
    status = request.args.get("status", "PENDING")
    results = get_work_orders_by_status(status)
    return jsonify({"work_orders": results}), 200

@app.get("/api/requests/incoming-with-workorders")
def api_incoming_requests_with_workorders():
    statuses = ["CRT", "PENDING", "IN-PROGRESS","INSPECTION_COMPLETED"]

    req_docs = (
        db.collection("requests")
        .where("status", "in", statuses)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )

    results = []

    for req in req_docs:
        req_data = req.to_dict()
        request_id = req_data["requestId"]

        # Fetch work orders for this request
        wo_docs = (
            db.collection("work_orders")
            .where("requestId", "==", request_id)
            .stream()
        )

        work_orders = [wo.to_dict() for wo in wo_docs]

        results.append({
            **req_data,
            "work_orders": work_orders
        })

    return jsonify({"incoming_requests": results}), 200

@app.get("/api/customer/request-status")
def api_customer_request_status():
    request_id = request.args.get("requestId")

    if not request_id:
        return jsonify({"error": "requestId is required"}), 400

    # Fetch request
    req_ref = db.collection("requests").document(request_id)
    req_doc = req_ref.get()

    if not req_doc.exists:
        return jsonify({"error": "Request not found"}), 404

    request_data = req_doc.to_dict()

    # Fetch work orders
    wo_docs = (
        db.collection("work_orders")
        .where("requestId", "==", request_id)
        .stream()
    )
    work_orders = [wo.to_dict() for wo in wo_docs]

    # Fetch purchase orders
    po_docs = (
        db.collection("purchase_orders")
        .where("requestId", "==", request_id)
        .stream()
    )
    purchase_orders = [po.to_dict() for po in po_docs]

    return jsonify({
        "request": request_data,
        "work_orders": work_orders,
        "purchase_orders": purchase_orders
    }), 200


# ---------------------------------------------------------
# Run Local Server
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
