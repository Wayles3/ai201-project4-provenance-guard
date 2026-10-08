"""Run with `pytest test_app.py`. Uses a temp DB and Flask's test client, so no server or API key is needed."""
import datetime
import pytest

import app as appmod

HUMAN = ("My grandmother never measured anything. She'd grab a fistful of flour, squint at the window "
         "like the light would tell her something, and say it was ready. I still can't make her bread taste right.")
AI = ("In today's rapidly evolving digital landscape, it is crucial to understand that effective communication "
      "serves as the cornerstone of success. Furthermore, leveraging innovative strategies fosters a holistic, "
      "resilient future. In conclusion, a comprehensive approach ensures seamless progress.")
LIVE = ("Last night I made a pot of chili and, honestly, I got the beans wrong. I forgot to soak them, so we ate "
        "late. My roommate didn't mind, she was busy anyway. It was still pretty good, I think, just crunchy. "
        "Next time I'll start earlier and I won't skip the cumin.")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(appmod, "get_llm_signal_score", lambda text: None)  # deterministic: no network
    appmod.limiter.enabled = False
    appmod.init_db()
    return appmod.app.test_client()


def submit(client, text=HUMAN, **extra):
    return client.post("/submit", json={"creator_id": "u1", "text": text, **extra})


def test_submit_valid(client):
    d = submit(client).get_json()
    assert d["attribution"] == "likely_human"
    assert d["signals"]["llm"] is None            # dropped, not faked as 0.5
    assert d["label"].startswith("Human-Authored Content")


def test_ai_text_flagged(client):
    d = submit(client, AI).get_json()
    assert d["attribution"] == "likely_ai"
    assert "verification" not in d


def test_missing_fields(client):
    assert client.post("/submit", json={"text": "Hello"}).status_code == 400
    assert client.post("/submit", json={"creator_id": "u", "text": "x", "content_type": "video"}).status_code == 400


def test_weights_renormalize():
    assert appmod.combine_signals({"llm": None, "phrase": 0.5, "stylometric": 0.5, "entropy": 0.5, "metadata": None}) == 0.5
    assert appmod.combine_signals({"llm": 1.0, "phrase": 0.0, "stylometric": 0.0, "entropy": 0.0, "metadata": None}) == 0.47


def test_thresholds_and_labels():
    assert appmod.resolve_attribution_and_label(0.70)[0] == "likely_ai"
    assert appmod.resolve_attribution_and_label(0.69)[0] == "uncertain"
    assert appmod.resolve_attribution_and_label(0.40)[0] == "uncertain"
    assert appmod.resolve_attribution_and_label(0.39)[0] == "likely_human"


def test_multimodal_metadata_changes_score(client):
    caption = "A photo of a lighthouse at dusk."
    plain = submit(client, caption, content_type="image_description").get_json()
    ai_meta = submit(client, caption, content_type="image_description",
                     image_metadata={"software": "Midjourney v6"}).get_json()
    cam_meta = submit(client, caption, content_type="image_description",
                      image_metadata={"camera_model": "Canon R5"}).get_json()
    assert plain["signals"]["metadata"] is None
    assert ai_meta["signals"]["metadata"] == 0.95
    assert ai_meta["confidence"] > plain["confidence"] > cam_meta["confidence"]
    assert ai_meta["content_type"] == "image_description"


def test_appeal_flow_and_display(client):
    cid = submit(client, AI).get_json()["content_id"]
    assert client.post("/appeal", json={"content_id": "nope", "creator_reasoning": "x"}).status_code == 404
    assert client.post("/appeal", json={"content_id": cid}).status_code == 400
    r = client.post("/appeal", json={"content_id": cid, "creator_reasoning": "I wrote this."})
    assert r.get_json()["status"] == "under_review"
    view = client.get(f"/content/{cid}").get_json()
    assert "appeal_notice" in view
    entry = client.get("/log").get_json()["entries"][0]
    assert entry["appealed_at"] and entry["appeal_reasoning"] == "I wrote this."


def test_certificate_flow(client):
    cid = submit(client).get_json()["content_id"]
    ch = client.post("/verify/challenge", json={"content_id": cid, "creator_id": "u1"}).get_json()
    assert client.post("/verify/challenge", json={"content_id": cid, "creator_id": "someone_else"}).status_code == 404

    short = client.post("/verify", json={"challenge_id": ch["challenge_id"], "live_sample": "too short"})
    assert short.status_code == 400

    res = client.post("/verify", json={"challenge_id": ch["challenge_id"], "live_sample": LIVE}).get_json()
    assert res["verified"] is True
    cert = res["certificate_id"]
    assert client.post("/verify", json={"challenge_id": ch["challenge_id"], "live_sample": LIVE}).status_code == 409

    assert client.get(f"/verify/{cert}").get_json()["valid"] is True
    assert client.get("/verify/PROV-HUMAN-fake-0000").status_code == 404
    view = client.get(f"/content/{cid}").get_json()
    assert view["badge"].startswith("Verified Human Credential")


def test_certificate_rejects_ai_live_sample_and_ai_content(client):
    cid = submit(client).get_json()["content_id"]
    ch = client.post("/verify/challenge", json={"content_id": cid, "creator_id": "u1"}).get_json()
    res = client.post("/verify", json={"challenge_id": ch["challenge_id"], "live_sample": AI + " " + AI}).get_json()
    assert res["verified"] is False

    ai_id = submit(client, AI).get_json()["content_id"]
    assert client.post("/verify/challenge", json={"content_id": ai_id, "creator_id": "u1"}).status_code == 403


def test_certificate_tamper_and_expiry(client):
    cid = submit(client).get_json()["content_id"]
    ch = client.post("/verify/challenge", json={"content_id": cid, "creator_id": "u1"}).get_json()
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)).isoformat()
    conn = appmod.db(); conn.execute("UPDATE challenges SET created_at = ?", (old,)); conn.commit(); conn.close()
    assert client.post("/verify", json={"challenge_id": ch["challenge_id"], "live_sample": LIVE}).status_code == 410


def test_analytics_and_dashboard(client):
    submit(client); submit(client, AI)
    d = client.get("/analytics/data").get_json()
    assert d["total_submissions"] == 2
    assert d["classifications"]["likely_ai"] == 1 and d["classifications"]["likely_human"] == 1
    assert sum(d["confidence_histogram"].values()) == 2
    assert "verified_human_count" in d
    page = client.get("/analytics")
    assert page.status_code == 200 and b"Provenance Guard Analytics" in page.data


def test_rate_limit(client):
    appmod.limiter.enabled = True
    appmod.limiter.reset()
    codes = [submit(client).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and 429 in codes[10:]
    appmod.limiter.enabled = False
