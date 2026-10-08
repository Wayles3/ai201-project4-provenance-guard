┌─────────────────────────┐
                   │      Client Request     │
                   └────────────┬────────────┘
                                │
                                ▼
                   ┌─────────────────────────┐
                   │  Flask-Limiter Middleware│ (10 req/min, 100 req/day)
                   └────────────┬────────────┘
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ Multi-Signal Ensemble Engine │
                 └──────────────┬───────────────┘
                                │
┌──────────────────┬────────────┴─────────────┬──────────────────┐
│                  │                          │                  │
▼                  ▼                          ▼                  ▼
┌──────────────┐ ┌─────────────┐          ┌──────────────┐ ┌──────────────────┐
│ Signal 1:    │ │ Signal 2:   │          │ Signal 3:    │ │ Signal 4:        │
│ Groq LLM API │ │ Stylometrics│          │ Perplexity & │ │ Multi-Modal      │
│ (Llama 4)    │ │ (Variance)  │          │ Entropy      │ │ EXIF / Metadata  │
└──────┬───────┘ └──────┬──────┘          └──────┬───────┘ └────────┬─────────┘
│                │                        │                  │
└────────────────┴───────────┬────────────┴──────────────────┘
│
▼
┌──────────────────────────────┐
│  Weighted Scoring & Calib.   │
│  C = Σ (w_i * S_i)           │
└──────────────┬───────────────┘
│
┌───────────────────────────┼───────────────────────────┐
▼                           ▼                           ▼
┌──────────────┐            ┌──────────────┐            ┌──────────────┐
│ Likely Human │            │  Uncertain   │            │  Likely AI   │
│ (C <= 0.39)  │            │ (0.40 - 0.69)│            │ (C >= 0.70)  │
└──────┬───────┘            └──────┬───────┘            └──────┬───────┘
│                            │                          │
│ (Generates Certificate     │                          │
│  if C <= 0.30)             │                          │
└────────────────────────────┼──────────────────────────┘
│
▼
┌──────────────────────────────┐
│   SQLite Database Audit Log  │
└──────────────┬───────────────┘
│
▼
┌──────────────────────────────┐
│     Unified JSON Response    │
└──────────────────────────────┘

### Flow Narratives

1. **Submission & Multi-Modal Classification Flow (`POST /submit`):**
   - The platform client submits a text payload (poem, story, excerpt) or a multi-modal payload containing structured image metadata alongside text.
   - The request passes through **Flask-Limiter** rate limits (10 req/min, 100 req/day per IP).
   - The payload is concurrently dispatched to the **Ensemble Pipeline**:
     - **Signal 1:** Groq LLM API (`meta-llama/llama-4-scout-17b-16e-instruct`) for holistic semantic analysis ($S_{\text{llm}}$).
     - **Signal 2:** Pure Python Stylometrics (Sentence length variance & Type-Token Ratio) ($S_{\text{sty}}$).
     - **Signal 3:** Perplexity & Structural Entropy heuristic ($S_{\text{ent}}$).
     - **Signal 4 (Multi-Modal):** EXIF/Metadata verification for image descriptions/assets ($S_{\text{meta}}$).
   - The **Ensemble Scoring Engine** computes a weighted, calibrated score ($C \in [0.0, 1.0]$) reflecting genuine uncertainty.
   - If $C \le 0.30$, a **Verified Human Provenance Certificate** cryptographically signed payload (`PROV-HUMAN-[UUID]-[SHA256_HASH]`) is generated.
   - The decision maps to one of three verbatim **Transparency Labels**, appends a structured record to the SQLite `audit_log`, and returns a unified JSON payload.

2. **Appeals Flow (`POST /appeal`):**
   - A creator contesting a classification submits `POST /appeal` containing `content_id` and `creator_reasoning`.
   - The system verifies `content_id` existence in SQLite, updates `status` from `"classified"` to `"under_review"`, appends the appeal event to `audit_log`, and returns confirmation.

3. **Analytics Pipeline (`GET /analytics/data`):**
   - Reads aggregated records from `audit_log` to calculate overall classification distribution, appeal rates, and mean confidence trends.

4. **Audit Log Access (`GET /log`):**
   - Exposes complete audit history including timestamps, signal breakdowns, creator IDs, text excerpts, certificate IDs, and appeal statuses in reverse chronological order.

---

## 1. Multi-Signal & Ensemble Detection Pipeline

To prevent single-point detection failure, Provenance Guard uses an ensemble of four independent signals:

| Signal ID | Name | Property Captured | Divergence / Blind Spots |
| :--- | :--- | :--- | :--- |
| **Signal 1** | Groq LLM Classifier (`llama-4-scout`) | Semantic cohesion, structural alignment, and typical LLM phrasing patterns. | Overly formal, highly structured human academic writing may be misflagged as AI. |
| **Signal 2** | Python Stylometrics | Structural variance: Sentence length standard deviation (burstiness) and Type-Token Ratio (vocabulary diversity). | Short passages (<50 words) provide insufficient statistical sample size. |
| **Signal 3** | Perplexity & Entropy Heuristic | Character/word-level entropy and transition predictability. | Technical documentation or code snippets naturally exhibit low entropy. |
| **Signal 4** | Multi-Modal Metadata Signal | Software signatures, EXIF headers, and creation timestamps for attached image metadata. | Stripped metadata or scrubbed header files default to neutral weight. |

### Ensemble Weighting Formula
The final calibrated confidence score $C$ is computed using normalized signal outputs $S_i \in [0.0, 1.0]$:

$$C = (0.45 \times S_{\text{llm}}) + (0.25 \times S_{\text{sty}}) + (0.20 \times S_{\text{ent}}) + (0.10 \times S_{\text{meta}})$$

---

## 2. Uncertainty Representation & Score Calibration

Confidence scores represent genuine continuous probability, explicitly avoiding binary flips at $0.50$.

- **Calibration & Thresholds:**
  - `0.00 - 0.39` $\rightarrow$ **High-Confidence Human (`likely_human`)**: High structural variance, high lexical entropy, low LLM probability.
  - `0.40 - 0.69` $\rightarrow$ **Uncertain / Borderline (`uncertain`)**: Divergent signal outputs (e.g., high LLM score but extreme stylometric variance). Protects authors from false positives.
  - `0.70 - 1.00` $\rightarrow$ **High-Confidence AI (`likely_ai`)**: High semantic alignment with LLM patterns, uniform sentence length, low entropy.

### Asymmetry Principles
A false positive (flagging a human creator's work as AI) damages trust far more than a false negative. Therefore, the threshold for `likely_ai` is set strictly at $\ge 0.70$, routing all ambiguous borderline content ($0.40 - 0.69$) into the protected `uncertain` category.

---

## 3. Transparency Label Variants (Verbatim Text)

The system surfaces three distinct plain-language labels based on score calibration:

### Variant 1: High-Confidence AI (`likely_ai`)
> "AI-Generated Content: This submission exhibits strong statistical and structural characteristics typical of AI language models. Context provided for platform transparency."

### Variant 2: High-Confidence Human (`likely_human`)
> "Human-Authored Content: Analysis indicates organic structural variance and stylistic characteristics consistent with human writing."

### Variant 3: Uncertain Attribution (`uncertain`)
> "Uncertain Attribution: Detection signals yielded mixed or non-conclusive results. Placed in neutral status to protect author attribution."

---

## 4. Appeals Workflow & Edge Cases

### Appeals Process
1. Creator submits `POST /appeal` with `content_id` and detailed `creator_reasoning`.
2. Database validates `content_id` and updates record `status` from `classified` to `under_review`.
3. An audit event is recorded logging the timestamp, creator reasoning, and snapshot of original signal scores.
4. Human moderation queue surfaces all records where `status == 'under_review'`.

### Anticipated Edge Cases
1. **Non-Native English Formal Writing:**
   - *Scenario:* A human non-native speaker uses formal, repetitive grammatical templates learned in structured English coursework.
   - *System Behavior:* Stylometrics may score low variance (AI-like), but LLM entropy signals remain neutral. Combined score falls in the `0.45 - 0.60` range (`uncertain`), protecting the author from false AI classification.
2. **Constrained Literary Forms (Sonnets, Villanelles, Repetitive Refrains):**
   - *Scenario:* Poetry relying on rigid meter, uniform line lengths, and intentional repetition.
   - *System Behavior:* Signal 2 detects low sentence variance. However, Signal 1 identifies creative context and high semantic nuance, balancing the ensemble score into `uncertain` or `likely_human`.

---

## 5. Stretch Feature Specifications

### A. Ensemble Detection
Combines 4 distinct signals (LLM, Stylometrics, Entropy, and Multi-Modal Metadata) weighted by empirical reliability ($0.45, 0.25, 0.20, 0.10$).

### B. Provenance Certificate ("Verified Human")
Content scoring $\le 0.30$ on confidence generates a verifiable cryptographic SHA-256 certificate payload embedded in response output:
- **Format:** `PROV-HUMAN-[UUID]-[SHA256_HASH]`
- **Display Label:** `"Verified Human Credential: Earned via multi-signal organic provenance validation."`

### C. Analytics Dashboard Endpoint (`GET /analytics/data`)
Surfaces aggregate system telemetry:
- Total submissions processed.
- Classifications breakdown (`likely_ai`, `likely_human`, `uncertain`).
- Appeal submission rate percentage.
- Average confidence score across all submissions.

### D. Multi-Modal Support
Extends `POST /submit` payload schema to accept optional `image_metadata` JSON objects (camera metadata, software edit signatures, generative AI header tags) alongside text content.

---

## 6. Database Schema Specification

### SQLite Database: `provenance_guard.db` — Table: `audit_log`

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `content_id` | TEXT | PRIMARY KEY | Unique UUIDv4 assigned to each submission. |
| `creator_id` | TEXT | NOT NULL | ID of the submitting author or application client. |
| `text_excerpt` | TEXT | NOT NULL | Truncated first 100 characters of submitted text. |
| `confidence` | REAL | NOT NULL | Calibrated ensemble confidence score $C \in [0.0, 1.0]$. |
| `attribution` | TEXT | NOT NULL | Final label (`likely_human`, `uncertain`, `likely_ai`). |
| `status` | TEXT | NOT NULL | Lifecycle state (`classified`, `under_review`, `resolved`). |
| `llm_score` | REAL | NOT NULL | Signal 1: Groq LLM evaluation score. |
| `stylometric_score` | REAL | NOT NULL | Signal 2: Structural burstiness & TTR score. |
| `entropy_score` | REAL | NOT NULL | Signal 3: Character & token entropy score. |
| `metadata_score` | REAL | NOT NULL | Signal 4: Multi-modal metadata EXIF score. |
| `certificate_id` | TEXT | NULLABLE | Cryptographic SHA-256 credential string if $C \le 0.30$. |
| `appeal_reasoning` | TEXT | NULLABLE | Written justification submitted by creator during appeal. |
| `timestamp` | DATETIME | DEFAULT CURRENT_TIMESTAMP | ISO-8601 UTC timestamp of submission. |

---

## 7. AI Tool Plan & Development Milestones

### Milestone 3 (Submission Endpoint & Signal 1)
- **Input Spec:** Architecture Diagram + Signal 1 specification.
- **Prompt Deliverables:** Flask app skeleton, Groq API client integration, basic SQLite logger.
- **Verification:** Execute `curl POST /submit` with sample inputs; verify response structure and SQLite row insertion.

### Milestone 4 (Ensemble Signals & Scoring Engine)
- **Input Spec:** Multi-Signal Pipeline + Ensemble Weighting Formula + Calibration Thresholds.
- **Prompt Deliverables:** Stylometric parser function, Entropy calculation function, weighted score combination function.
- **Verification:** Run benchmark test inputs (Clearly AI, Clearly Human, Academic Formal, Constrained Poetry) and confirm calibrated score outputs match expected ranges.

### Milestone 5 (Production Layer & Stretch Features)
- **Input Spec:** Transparency Labels + Appeals Spec + Rate Limiting Config + Stretch Specs.
- **Prompt Deliverables:** Flask-Limiter routing, `POST /appeal` endpoint, Provenance Certificate generator, `GET /analytics/data` endpoint, `GET /log` endpoint.
- **Verification:** Trigger HTTP 429 rate limiting; verify status updates on `/appeal`; check analytics aggregations on `/analytics/data`.
---

## 8. Revision 2 (post-implementation review, before stretch work)

Measuring v1 against a hand-built sample set showed problems; the design changes below supersede sections 1-2 and 5B where they conflict.

**Findings**
- Obvious AI text topped out at C = 0.55-0.61, so `likely_ai` was unreachable. Cause: the char-entropy signal returned 0.2 for all English and the stylometric signal sat near 0.6 for everything.
- Formal human prose (an academic abstract) got LLM = 0.85, a false-positive risk.
- The Groq model in section 1 (`llama-4-scout`) was retired; default is now `openai/gpt-oss-20b` (env `GROQ_MODEL`).
- Metadata was logged but never scored; the 0.10 weight in section 1 was not implemented.

**Changes**
1. **Signals (5):** LLM judge, stylometrics (now adds *burstiness* = sentence-length coefficient of variation and contraction use, as the spec originally promised), AI-phrase density (new: clichés such as "furthermore", "in conclusion", "tapestry", "crucial"), char entropy (kept, demoted), metadata (only when supplied).
2. **Weighting = weighted average over the signals that are *available*:** llm 0.45, phrase 0.25, stylometric 0.20, entropy 0.05, metadata 0.15. Missing signals (no API key, LLM failure, no image metadata) are dropped and the rest renormalized, which replaces the old two-formula branch. The response reports `llm_available`.
3. **Meaning of 0.5:** "the signals don't know" — not "50% AI". Thresholds are unchanged (<=0.39 human, >=0.70 AI) and deliberately asymmetric to protect human authors.
4. **Appeal time** is now recorded (`appealed_at`); labels on appealed content get an "under review" notice.

## 9. Stretch feature specs

### A. Ensemble detection
Already the core pipeline; now 5 signals with the weighted-average-over-available-signals rule above. Documented in README with validation table.

### B. Provenance certificate (verified human) — redesigned
v1 auto-issued a certificate at C <= 0.30. That is not "earned through an additional verification step". New flow:
1. `POST /verify/challenge {content_id, creator_id}` — allowed only if the content is not `likely_ai`; returns a random writing prompt and `challenge_id` (valid 15 min, single use).
2. `POST /verify {challenge_id, live_sample}` — creator writes >= 40 words on the prompt. The sample is run through the same ensemble and must classify `likely_human` (C <= 0.39).
3. On success the server issues `PROV-HUMAN-<id8>-<HMAC-SHA256(secret, content_id|creator_id|issued_at)[:16]>`, stored on the row with `verified_at`.
4. `GET /verify/<certificate_id>` re-computes the HMAC (tamper check). `GET /content/<content_id>` is the public view: label plus the badge "Verified Human" when a certificate exists.
Limits: this proves the creator can write human-looking text live, not that the earlier text is theirs. Documented as a limitation.

### C. Analytics dashboard
`GET /analytics` renders an HTML page from `GET /analytics/data`: classification split, appeal rate, plus additional metrics: confidence histogram (5 buckets), verified-human count, and LLM-vs-heuristics disagreement rate (a signal-health indicator).

### D. Multi-modal
`POST /submit` accepts `content_type` (`text` default, or `image_description`) and optional `image_metadata` (software, camera_model, exif_data, c2pa/ai flags). For `image_description` the text is the caption/alt-text, and the metadata signal is included in the ensemble. Content type is stored in the audit log.
