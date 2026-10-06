import pytest
import requests

BASE_URL = "http://127.0.0.1:5001"

def test_submit_valid():
    payload = {
        "creator_id": "test_user_01",
        "text": "Yesterday I walked to the park and saw a golden retriever chasing a red ball."
    }
    res = requests.post(f"{BASE_URL}/submit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "content_id" in data
    assert data["attribution"] in ["likely_human", "uncertain", "likely_ai"]
    assert "signals" in data

def test_submit_missing_fields():
    res = requests.post(f"{BASE_URL}/submit", json={"text": "Hello"})
    assert res.status_code == 400

def test_appeal_flow():
    # 1. Create content
    submit_res = requests.post(f"{BASE_URL}/submit", json={
        "creator_id": "test_user_02",
        "text": "The quick brown fox jumps over the lazy dog."
    }).json()
    
    content_id = submit_res["content_id"]
    
    # 2. Submit appeal
    appeal_res = requests.post(f"{BASE_URL}/appeal", json={
        "content_id": content_id,
        "creator_reasoning": "This is entirely my organic writing."
    })
    assert appeal_res.status_code == 200
    assert appeal_res.json()["status"] == "under_review"

def test_analytics():
    res = requests.get(f"{BASE_URL}/analytics/data")
    assert res.status_code == 200
    data = res.json()
    assert "total_submissions" in data
    assert "classifications" in data

def test_audit_log():
    res = requests.get(f"{BASE_URL}/log")
    assert res.status_code == 200
    assert "entries" in res.json()
