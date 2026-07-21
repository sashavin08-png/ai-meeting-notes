# AI Meeting Notes — Session 1: Auth + Transcription + Summarization

Upload a recording, get a transcript, an AI-written summary, and a list of
action items — tied to a real user account with its own login, not a
shared password like the earlier receptionist platform's dashboard.

## What's built

- **`core/db.py`** — users (with hashed passwords) and meetings, SQLite
  locally / Postgres in production (same auto-switching pattern as the
  receptionist platform)
- **`core/transcriber.py`** — audio → text using a locally-run Whisper
  model (`openai-whisper`), free — no per-minute API cost, at the expense
  of speed and server load compared to a paid transcription API
- **`core/summarizer.py`** — transcript → summary + action items via
  Claude API
- **`core/json_utils.py`** — the same battle-tested robust JSON parser
  from the receptionist platform (handles markdown-wrapped JSON, stray
  prose, unescaped control characters)
- **`app.py`** — Flask app: register / login / logout (real password
  hashing via werkzeug, not a shared dashboard password), upload, meeting
  list, meeting detail — each user only ever sees their own meetings
- Free plan capped at 3 meetings/month (`FREE_PLAN_MONTHLY_LIMIT` in
  `app.py`) — foundation for the Stripe paid tier coming in Session 3

## What was tested (and how)

Everything **except the actual Whisper transcription call** was tested
end-to-end with a real Flask test client:
- registration, including password-length validation and duplicate-email
  rejection
- login with correct and incorrect passwords
- logged-out users get redirected instead of seeing meetings
- upload flow end-to-end (with `transcriber`/`summarizer` mocked)
- **data isolation**: a second user cannot open the first user's meeting
  (404, not an error page leaking data)
- **free plan quota**: the 4th upload in a month is blocked with a clear
  message

⚠️ **`core/transcriber.py` itself was not run against a real audio file**
in the environment this was built in — Whisper needs to download its model
weights from a domain this sandbox's network couldn't reach. The code was
reviewed carefully and follows the library's documented usage exactly, but
test it for real the same way earlier projects' untested paths were
verified — try uploading an actual short recording once you have this
running locally.

## Try it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY='sk-ant-...'
python app.py
```

Open **http://localhost:5090**, sign up, and upload a short audio
recording (even a 10-second voice memo is enough to see the pipeline
work). The first upload will be slow — Whisper downloads its model file
(~140MB for the "base" model) the first time it runs.

## What's next

Nothing pressing — the platform is functional end to end, locally and
now deployed.

---

## Session 4: Switching to Groq + deploying to Render

### Why Groq instead of local Whisper for the deployed version

Self-hosted Whisper needs real RAM (1-2GB+) — more than a free-tier
cloud instance (typically 512MB) comfortably provides. Rather than risk
out-of-memory crashes in production, `core/transcriber.py` now checks
for `GROQ_API_KEY` first: if set, transcription happens via Groq's
hosted Whisper API (fast, generous free tier, and doesn't touch your own
server's RAM at all). If not set, it falls back to the local Whisper
model — handy for local development without needing a Groq account.

**Speaker diarization** (`core/diarizer.py`, `pyannote.audio`) doesn't
have a lightweight hosted-API equivalent wired in yet, so it remains a
local-development-only feature for now — it's simply skipped in
production (same graceful fallback as before, nothing breaks).

`requirements.txt` no longer includes `openai-whisper` or
`pyannote.audio` — they're heavy and unnecessary for the deployed
version. They've moved to `requirements-local.txt` for anyone who wants
local transcription/diarization without Groq or the cloud at all:
```bash
pip install -r requirements.txt -r requirements-local.txt
```

### Setup: Groq

1. Create a free account at [console.groq.com](https://console.groq.com)
2. Create an API key
3. `export GROQ_API_KEY='gsk_...'`

### Deploying to Render

Same pattern as the AI Receptionist Platform project:

1. **Postgres** — New + → Postgres, free plan, copy the Internal Database URL
2. **Web Service** — New + → Web Service, connect this repo:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`
   - Environment variables:
     - `DATABASE_URL` = the Postgres URL
     - `ANTHROPIC_API_KEY`
     - `GROQ_API_KEY`
     - `FLASK_SECRET_KEY` = any long random string (used to sign login sessions)
     - `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`
3. Deploy, note the public URL Render gives you

### Update the Stripe webhook URL

The webhook was pointed at a placeholder URL during Session 3 testing.
Go back to the Stripe Dashboard → Developers → Webhooks → your endpoint,
and update its URL to:
```
https://<your-render-url>/billing/webhook
```

### What to test

- Register a new account on the *deployed* URL, upload a short recording
  — confirm it transcribes via Groq (check Render's logs for the request)
- Download the PDF, try "Share via email"
- Click "Upgrade to unlimited", pay with Stripe's test card
  `4242 4242 4242 4242` — confirm the account shows as `paid` afterward
  (this is the real end-to-end test of the webhook now pointing at the
  right URL)
- Restart the Web Service and confirm past meetings are still there
  (proof Postgres is actually persisting data)

---

## Session 3: Stripe billing

Real paid plans instead of a hardcoded free limit. Users click "Upgrade",
pay via Stripe's own hosted checkout page (this app never sees or
touches card details), and their account is automatically upgraded —
including automatic downgrade if they cancel later.

### What was tested (and how)

Stripe's actual API (`api.stripe.com`) wasn't reachable in the sandbox
this was built in, so the checkout/portal creation calls themselves
couldn't be run live — same situation as Whisper's model download and
pyannote's gated model earlier. **What *could* be tested locally, and
was tested thoroughly:**

- **Webhook signature verification** — this is pure local cryptography
  (HMAC), no network needed. Verified: a correctly-signed event is
  accepted; a forged signature is rejected; a tampered payload under an
  otherwise-valid signature is rejected; a replayed old signature
  (10 minutes old) is rejected
- **The full plan lifecycle**, via a real Flask test client with signed
  test webhook events: `checkout.session.completed` correctly upgrades
  a user to `paid` and stores their Stripe customer id; the free plan's
  monthly limit no longer applies once upgraded (5 uploads in a row,
  no blocking); `customer.subscription.deleted` correctly downgrades
  back to `free`
- Along the way, a real bug was caught and fixed: newer versions of the
  `stripe` library return event data as a `StripeObject`, not a plain
  dict — `dict(stripe_object)` silently fails in an unexpected way;
  `.to_dict()` is the correct conversion

**Not tested here** — actually redirecting to Stripe's hosted checkout
page and completing a real (test-mode) payment. Do this yourself once
it's running, using Stripe's test card `4242 4242 4242 4242` (any future
expiry, any CVC).

### Setup

1. Create a free [Stripe](https://stripe.com) account (test mode needs
   no real business details to start)
2. Create a Product with a recurring monthly Price — copy its Price ID
3. Get your test-mode secret key from the Stripe dashboard
4. Set up a webhook endpoint pointing at `/billing/webhook`, listening for
   `checkout.session.completed` and `customer.subscription.deleted` —
   copy its signing secret

```bash
export STRIPE_SECRET_KEY='sk_test_...'
export STRIPE_PRICE_ID='price_...'
export STRIPE_WEBHOOK_SECRET='whsec_...'
```

For local testing, use the [Stripe CLI](https://stripe.com/docs/stripe-cli)
to forward webhook events to your local server:
```bash
stripe listen --forward-to localhost:5090/billing/webhook
```
(this also prints a webhook signing secret to use locally)

### What to test yourself

- Click "Upgrade to unlimited" as a free-plan user — should redirect to
  Stripe's hosted checkout
- Complete a test payment with `4242 4242 4242 4242` — should redirect
  back and (within a few seconds, once the webhook arrives) show as
  `paid` on the account
- Try uploading more than 3 recordings in a month as the now-paid
  account — should not be blocked
- Click "Manage billing" — should reach Stripe's hosted portal; cancel
  the subscription there — the account should downgrade back to `free`
  once Stripe sends the cancellation webhook

---

## Session 2: Speaker diarization + export

### Speaker diarization ("who said what")

Whisper transcribes speech but has no concept of separate speakers.
`core/diarizer.py` adds that, using `pyannote.audio` — merging its output
with Whisper's timestamped segments into a labeled transcript:

```
[SPEAKER_00] Let's start with the timeline.
[SPEAKER_01] Sure, I think we can hit Friday.
```

The segment-merging logic was tested thoroughly with synthetic data
(including edge cases — gaps between speaker turns, a speaker returning
later in the conversation) since the actual pyannote model couldn't be
downloaded in the sandbox this was built in (no network access to
huggingface.co there). **Test the real model yourself** the same way
Whisper itself was verified earlier.

**One-time setup (free):**
1. Create an account at [huggingface.co](https://huggingface.co)
2. Visit `huggingface.co/pyannote/speaker-diarization-3.1` while logged in
   and accept the model's terms
3. Create an access token at `huggingface.co/settings/tokens`
4. `export HUGGINGFACE_TOKEN='hf_...'`

If `HUGGINGFACE_TOKEN` isn't set, diarization is skipped automatically —
uploads still work, just without speaker labels. If diarization fails for
any reason (bad audio, model error), the app falls back to the plain
transcript rather than losing the upload entirely.

### PDF export & email sharing

- **`core/exporter.py`** — generates a formatted PDF (summary, action
  items, full transcript) using `fpdf2`. Uses a Unicode font (DejaVu Sans,
  if available on the system) so non-Latin transcripts — Russian,
  Ukrainian, etc. — render correctly instead of erroring or dropping
  characters.
- **"Share via email"** — a plain `mailto:` link pre-filling the subject
  and body with the summary and action items. No email server, no SMTP
  credentials, no cost — it just opens whatever email client the person
  already has configured.

### What to test

- Upload a recording with two distinct voices (or two people talking) with
  `HUGGINGFACE_TOKEN` set — confirm the transcript shows `[SPEAKER_00]` /
  `[SPEAKER_01]` labels correctly
- Download the PDF for a meeting with non-English text — open it and
  confirm the characters render correctly, not as boxes or "?"
- Click "Share via email" — confirm it opens your email client with the
  summary pre-filled
- Try both PDF download and diarization as a *different* logged-in user —
  confirm neither leaks another user's meeting (403/404, not someone
  else's data)

## Stack

Python, Flask, Whisper (local), Claude API, SQLite/PostgreSQL
