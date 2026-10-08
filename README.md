# Provenance Guard

A Flask API that estimates whether submitted content was written by a human or an AI, shows the creator a plain-language transparency label, lets creators appeal, and lets them earn a "Verified Human" credential. Every decision is written to a SQLite audit log.

Design doc: [planning.md](planning.md) (sections 8-9 record the design changes and stretch-feature specs made after the first implementation).

## Run it

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo "GROQ_API_KEY=gsk_..." > .env     # optional. Also GROQ_MODEL, CERT_SECRET
python app.py                           # http://localhost:5001  (dashboard at /analytics)
pytest test_app.py                      # 12 tests; temp DB, no server or API key needed
```

Without a Groq key the LLM signal is dropped and the other signals are renormalized.

## Architecture overview

```
POST /submit {creator_id, text, content_type?, image_metadata?}
  -> Flask-Limiter (10/min, 100/day per IP)
  -> validate (400 on missing/invalid fields)
  -> 5 signals: LLM judge | stylometrics | AI-phrase density | char entropy | metadata (if supplied)
  -> weighted average over the signals that are available   -> confidence C in [0,1]
  -> thresholds -> attribution + transparency label
  -> INSERT into audit_log (SQLite)
  -> JSON {content_id, attribution, confidence, signals, label, status}

POST /appeal {content_id, creator_reasoning}
  -> status classified -> under_review; reasoning + appealed_at stored on the same row

POST /verify/challenge -> POST /verify -> GET /verify/<cert> / GET /content/<id>   (Verified Human, below)
```

All code is in [app.py](app.py); tests in [test_app.py](test_app.py).

## Detection signals

Each signal returns 0-1, where 1 means "looks AI". A signal that is unavailable returns `null` and is excluded, not faked as 0.5.

| Signal | Measures | Why | What it misses |
|---|---|---|---|
| **LLM judge** (Groq, `openai/gpt-oss-20b`, temp 0) | A model's estimate that the text is AI | Catches the overall "AI voice" that statistics can't | Formal human writing reads as AI (the academic abstract got 0.85). Varies across models and versions. |
| **Stylometrics** | Burstiness (sentence-length coefficient of variation), informal/first-person words and contractions, type-token ratio (only on 60+ words) | Cheap, offline, explainable. LLM text is evenly paced and formal. | Formal humans score "AI-like". Needs 3+ sentences for burstiness. English-only marker list. |
| **AI-phrase density** | Stock LLM phrasing ("furthermore", "in conclusion", "landscape", "holistic"...) per 100 words | Strong when present, since LLMs overuse these | Zero hits is only weak evidence (scores 0.25). AI text written plainly or as fiction/poetry has none. The list is my own and was written while looking at my samples (see Validation). |
| **Character entropy** | Shannon entropy of characters | Meant to flag degenerate text | Nearly all English falls in the same band, so it barely discriminates (0.2 on every sample). Weighted 0.05 for that reason. |
| **Metadata** | Image `software`, `camera_model`, `exif_data`, `ai_generated` flag | Gives non-text submissions a provenance hint | Missing/stripped metadata -> excluded. Forgeable. Can't decide a result alone (below). |

## Confidence scoring

A weighted average over available signals:

```
weights:  llm 0.45 | phrase 0.25 | stylometric 0.20 | entropy 0.05 | metadata 0.15
C = sum(w_i * s_i) / sum(w_i over signals that returned a value)
```

**What 0.5 means:** "the signals don't know", not "50% AI". `C >= 0.70` -> `likely_ai`; `C <= 0.39` -> `likely_human`; everything in between -> `uncertain`. The AI bar is deliberately high: calling a human's work AI costs more than missing an AI text, and the `uncertain` band is the buffer.

**Validation.** I scored 16 hand-picked texts (6 AI-style that I wrote to imitate LLM output, 10 human: casual, a sonnet, news, a non-native-style email, a formal abstract) offline and then live through the API; both runs matched. This is a sanity check on a small set, **not a benchmark**, and I changed the signals after seeing the first version's scores, so the numbers are optimistic.

| Group | Result |
|---|---|
| Human (10) | 9 `likely_human`, 1 `uncertain`, **0 flagged as AI** |
| AI (6) | 3 `likely_ai`, 1 `uncertain`, 2 `likely_human` (misses) |

Hand-checked rows:

| Sample | LLM | Phrase | Style | Entropy | **C** | Result |
|---|---|---|---|---|---|---|
| AI essay ("rapidly evolving digital landscape…") | 0.85 | 0.95 | 0.72 | 0.20 | **0.81** | likely_ai |
| AI product review | 0.70 | 0.95 | 0.74 | 0.20 | **0.75** | likely_ai |
| AI email ("Thank you for reaching out…") | 0.62 | 0.25 | 0.57 | 0.20 | **0.49** | uncertain |
| Formal human abstract | 0.85 | 0.25 | 0.71 | 0.20 | **0.63** | uncertain |
| Human story (grandmother's bread) | 0.15 | 0.25 | 0.27 | 0.20 | **0.20** | likely_human |
| AI short story (lighthouse) | 0.30 | 0.25 | 0.74 | 0.20 | **0.37** | likely_human (miss) |

**Two examples with noticeably different confidence**

- *High-confidence AI* (**C = 0.81**): "In today's rapidly evolving digital landscape, it is crucial to understand that effective communication serves as the cornerstone of success…" -> `likely_ai`.
- *Low-confidence / human* (**C = 0.20**): "My grandmother never measured anything. She'd grab a fistful of flour, squint at the window…" -> `likely_human`.
- For the in-between case, see the formal human abstract above: LLM says 0.85, the phrase signal says 0.25, and the ensemble lands at 0.63 (`uncertain`) instead of making a false accusation.

## Transparency label

Exact text returned in `label`:

- **High-confidence AI** (`likely_ai`): "AI-Generated Content: This submission exhibits strong statistical and structural characteristics typical of AI language models. Context provided for platform transparency."
- **Human** (`likely_human`): "Human-Authored Content: Analysis indicates organic structural variance and stylistic characteristics consistent with human writing."
- **Uncertain** (`uncertain`): "Uncertain Attribution: Detection signals yielded mixed or non-conclusive results. Placed in neutral status to protect author attribution."

Additional display elements, via `GET /content/<id>`: after an appeal the view adds "Under review: the creator has appealed this label and a human reviewer will re-check it."; a verified item adds the badge "Verified Human Credential: Earned via multi-signal organic provenance validation." I did not user-test the label wording with someone outside the project.

## Rate limiting

- `POST /submit`: **10 per minute, 100 per day** per IP. Each submit can trigger a paid LLM call. A person posting writing by hand rarely sends more than a few per minute; 10/min leaves headroom for retries but stops a script, and 100/day bounds the cost of sustained abuse from one address.
- `POST /verify/challenge` and `POST /verify`: **5 per minute** each, since every attempt scores a sample.
- Reads and `/appeal` are unlimited.
- Verified: a burst of 12 submits returned `[200 x10, 429, 429]`.
- Limits: counters are in memory, keyed by IP (resets on restart, not shared across workers, and users behind one NAT share a bucket). A real deployment needs Redis plus per-account limits.

## Audit log

One row per submission. Appeals update the same row (`status`, `appeal_reasoning`, `appealed_at`), and certificates add `certificate_id`/`verified_at`. Sample from the live run (`GET /log`, selected columns). The `.db` file is gitignored, so this is the evidence.

```
timestamp                         content_id  creator_id      type               attribution   conf  status        notes
2026-10-08T01:18:43.041596+00:00  83d224dd    ai_essay        text               likely_ai     0.81  classified
2026-10-08T01:19:27.667305+00:00  463492b2    human_story     text               likely_human  0.20  classified    certificate PROV-HUMAN-463492b2-F8C139DB694374F6
2026-10-08T01:20:05.102872+00:00  90491de3    human_academic  text               uncertain     0.63  under_review  appealed_at 2026-10-08T01:20:41.675052+00:00
                                                                                                                    reasoning: "I wrote this abstract myself for my sociology thesis; the formal register is required by the discipline."
2026-10-08T01:20:42.013537+00:00  c2412ae5    img_ai          image_description  uncertain     0.45  classified    metadata software=Midjourney v6
```

## Stretch features

### 1. Ensemble detection
Five signals combined with a documented weighted average that renormalizes over the available signals (formula above). This replaced v1's two hard-coded branches, so a missing API key or failed LLM call degrades gracefully, and the response says which signals were used (`null` = not used). Weights are judgment calls informed by the small validation set, not fitted values.

### 2. Provenance certificate ("Verified Human")
Earned through an additional step, not given automatically:
1. `POST /verify/challenge {content_id, creator_id}` - allowed if the creator owns the content and it isn't `likely_ai`. Returns a random writing prompt (valid 15 minutes, single use).
2. `POST /verify {challenge_id, live_sample}` - the creator writes 40+ words on the prompt. The sample goes through the same ensemble and must classify `likely_human`. Failing consumes the challenge.
3. On success the server issues `PROV-HUMAN-<id8>-<HMAC-SHA256(secret, content_id|creator_id|issued_at)[:16]>`.
4. `GET /verify/<certificate_id>` recomputes the HMAC to validate it. `GET /content/<id>` shows the badge next to the label.

Limits: it proves the creator can produce human-looking text on demand, not that the original piece is theirs (someone could use a human friend, or an AI text that scored as human could be verified). Set `CERT_SECRET` in production (the default is a dev value).

### 3. Analytics dashboard
`GET /analytics` (HTML, reads `GET /analytics/data`). It shows the classification split, **appeal rate**, average confidence, plus the additional metrics: a confidence histogram, verified-human count, and an **LLM-vs-heuristics disagreement rate** (share of submissions where the LLM and the stylometric/phrase signals differ by more than 0.35). That last one is a signal-health indicator: if it rises, one signal is drifting. Example JSON from the live run: 18 submissions, 3 likely_ai / 12 likely_human / 3 uncertain, 5.56% appeal rate, 1 verified, 5.56% disagreement.

### 4. Multi-modal support
`POST /submit` accepts `content_type: "image_description"` (a caption/alt text) and `image_metadata` (`software`, `camera_model`, `exif_data`, `ai_generated`). The metadata signal joins the ensemble only when supplied. Live result for the same caption: with `software: Midjourney v6` -> metadata 0.95, C = 0.45 (`uncertain`); with a Canon camera/EXIF -> metadata 0.10, C = 0.33 (`likely_human`). Metadata nudges the score but can't decide it alone: a short caption has little text evidence, and I'd rather route that to `uncertain`/review than make an automatic AI call from a forgeable field.

## Known limitations

- **Literary AI text is under-detected.** The AI lighthouse story and AI poem scored 0.37-0.38 (`likely_human`): no stock phrases, creative register, uneven sentences. Those could also earn a Verified Human credential, since verification only checks the live sample.
- **Formal human writing is pushed toward AI.** The academic abstract got an LLM score of 0.85 and landed at 0.63 (`uncertain`). Legal/technical prose and non-native speakers writing in textbook register carry the same risk. The 0.70 cutoff and the `uncertain` band exist for this, but the person still sees an "uncertain" label.
- **Evaluation is small and partly circular.** 16 samples, AI ones written by me, phrase list and weights tuned after looking at them. Real accuracy will be lower.
- **Short or non-English text** is unreliable for stylometrics; the marker lists are English-only.
- **Entropy signal is nearly inert.** It's kept at 0.05 weight for completeness.
- **Trivially evadable**: paraphrasing AI text, or lightly editing it with contractions, moves the heuristic signals toward "human".
- Only the first 100 characters of text are stored in the log. The rate limiter is in-memory and per IP.

## Spec reflection

- **Helped:** deciding thresholds and the false-positive asymmetry in [planning.md](planning.md) before coding made the 0.70 `likely_ai` cutoff, the `uncertain` band, and the three label texts settled decisions. When I later saw numbers, I knew which parts of the design to question (the signals) and which to keep (the thresholds).
- **Diverged:** (1) The spec's four-signal formula (`0.45/0.25/0.20/0.10`) wasn't implementable as written: metadata doesn't exist for text, and the entropy and stylometric signals didn't discriminate. I added a phrase-density signal and made the formula a weighted average over the available signals (planning.md section 8). (2) The spec called for the certificate to be issued automatically at C <= 0.30; the stretch requirement says "earned through an additional verification step", so I replaced that with the challenge flow. (3) The spec's Llama model was retired by Groq. I used `openai/gpt-oss-20b`. Note that `planning.md` was committed empty in the first commit, so git history cannot show it was written before implementation; sections 1-7 of it describe the original plan and sections 8-9 were added afterwards.

## AI usage

I used Claude Code throughout; these are the places where I directed it and changed what it produced.

1. **Scaffold and signals.** I had it generate the Flask app, SQLite logging, and signal functions from the planning.md spec. When I ran it on my samples, every result came back `uncertain` with the same 0.5 LLM score, and the stylometric/entropy signals were close to constant. I did not accept that as "working": I had it investigate, and we measured each signal separately before changing anything.
2. **Silent LLM failure.** The investigation found Groq had retired the model ID, and a bare `except` was hiding the 404 while returning 0.5, which made the score look like real data. We switched models, raised `max_tokens` (the new model is a reasoning model, so 10 tokens would return nothing), and changed failure to return `None`, so the signal is dropped from the ensemble and logged, instead of pretending to be neutral.
3. **Redesigning the certificate.** The generated certificate was issued automatically at low score, which I overrode: the assignment asks for an additional verification step, so I specified the challenge/live-sample/HMAC flow, single-use challenges, and expiry, and had tests written for tampering, reuse, and expiry.
4. **Honest evaluation.** I asked for a bigger sample set and directed that the README report the misses (literary AI text) and the fact that the signals were tuned after seeing the first scores, instead of presenting the best numbers.
5. **Route bug.** The generated file defined the `/` route after `app.run()`, so it never registered when started with `python app.py`; I had it moved above the entry point.
