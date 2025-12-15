# utils/pubsub_ops.py
import os
import json
from google.cloud import pubsub_v1

PROJECT_ID = os.getenv("PROJECT_ID")  # e.g. bigquerypractise-475707
REQUEST_TOPIC = os.getenv("REQUEST_TOPIC", "request-events")  # topic name
publisher = pubsub_v1.PublisherClient()
# topic path: projects/{project_id}/topics/{topic}
def _topic_path(topic_name: str):
    return publisher.topic_path(PROJECT_ID, topic_name)

def publish_request_event(payload: dict) -> bool:
    """
    Publish the given payload (dict) to the request-events topic.
    Returns True on success.
    """
    try:
        topic_path = _topic_path(REQUEST_TOPIC)
        data = json.dumps(payload).encode("utf-8")
        # attributes optional, not used here
        future = publisher.publish(topic_path, data)
        future.result(timeout=10)  # raise if publish failed
        return True
    except Exception as e:
        # In production you would log properly
        print("publish_request_event error:", e)
        return False

def publish_po_event(payload: dict) -> bool:
    """
    Same pattern for PO events if needed later.
    """
    try:
        topic_path = _topic_path(os.getenv("PO_TOPIC", "po-events"))
        data = json.dumps(payload).encode("utf-8")
        future = publisher.publish(topic_path, data)
        future.result(timeout=10)
        return True
    except Exception as e:
        print("publish_po_event error:", e)
        return False
