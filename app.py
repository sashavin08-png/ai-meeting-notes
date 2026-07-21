#!/usr/bin/env python3
"""
AI Meeting Notes — upload a recording, get a transcript, summary, and
action items, tied to a real user account.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY='sk-ant-...'
    python app.py
Then open http://localhost:5090
"""

import logging
import os
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from core import db, transcriber, summarizer, diarizer, exporter, billing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

FREE_PLAN_MONTHLY_LIMIT = 3
ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a", "mp4", "webm", "ogg"}

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-production")
db.init_db()


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return render_template("register.html")

        if db.get_user_by_email(email):
            flash("An account with this email already exists.")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        user_id = db.create_user(email=email, password_hash=password_hash)
        session["user_id"] = user_id
        return redirect(url_for("meetings_list"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = db.get_user_by_email(email)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.")
            return render_template("login.html")

        session["user_id"] = user["id"]
        return redirect(url_for("meetings_list"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def meetings_list():
    user = db.get_user(session["user_id"])
    meetings = db.list_meetings(user["id"])
    used_this_month = db.count_meetings_this_month(user["id"])
    return render_template(
        "meetings.html",
        user=user,
        meetings=meetings,
        used_this_month=used_this_month,
        monthly_limit=FREE_PLAN_MONTHLY_LIMIT,
    )


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    user = db.get_user(session["user_id"])

    if request.method == "POST":
        if user["plan"] == "free" and db.count_meetings_this_month(user["id"]) >= FREE_PLAN_MONTHLY_LIMIT:
            flash(f"Free plan limit reached ({FREE_PLAN_MONTHLY_LIMIT}/month). Upgrade to upload more.")
            return redirect(url_for("meetings_list"))

        file = request.files.get("audio_file")
        title = request.form.get("title", "").strip() or "Untitled meeting"

        if not file or file.filename == "":
            flash("Please choose an audio file.")
            return render_template("upload.html")

        if not allowed_file(file.filename):
            flash(f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
            return render_template("upload.html")

        meeting_id = db.create_meeting(user_id=user["id"], title=title)

        safe_name = secure_filename(file.filename)
        saved_path = UPLOAD_DIR / f"{meeting_id}_{safe_name}"
        file.save(saved_path)

        try:
            if os.environ.get("HUGGINGFACE_TOKEN"):
                # Speaker diarization is additive — if it fails for any reason
                # (bad audio, model hiccup, etc), fall back to the plain
                # transcript rather than losing the whole upload.
                try:
                    whisper_result = transcriber.transcribe_with_segments(str(saved_path))
                    transcript = diarizer.transcribe_with_speakers(
                        str(saved_path), whisper_result["segments"]
                    )
                except Exception:
                    logger.exception("Speaker diarization failed, falling back to plain transcript")
                    transcript = transcriber.transcribe_audio(str(saved_path))
            else:
                transcript = transcriber.transcribe_audio(str(saved_path))

            result = summarizer.summarize_transcript(transcript)
            action_items = result.get("action_items", [])
            db.update_meeting_result(
                meeting_id=meeting_id,
                transcript=transcript,
                summary=result.get("summary", ""),
                action_items="\n".join(action_items) if action_items else "",
            )
        except Exception as e:
            logger.exception("Failed to process meeting %s", meeting_id)
            db.mark_meeting_failed(meeting_id, str(e))
        finally:
            # Don't keep raw audio around longer than needed to transcribe it.
            saved_path.unlink(missing_ok=True)

        return redirect(url_for("meeting_detail", meeting_id=meeting_id))

    return render_template("upload.html")


@app.route("/meeting/<meeting_id>")
@login_required
def meeting_detail(meeting_id):
    meeting = db.get_meeting(meeting_id)
    if meeting is None or meeting["user_id"] != session["user_id"]:
        return "Meeting not found", 404
    return render_template("meeting_detail.html", meeting=meeting)


@app.route("/meeting/<meeting_id>/pdf")
@login_required
def meeting_pdf(meeting_id):
    meeting = db.get_meeting(meeting_id)
    if meeting is None or meeting["user_id"] != session["user_id"]:
        return "Meeting not found", 404
    if meeting["status"] != "done":
        return "Meeting isn't ready yet", 400

    pdf_bytes = exporter.generate_pdf(dict(meeting))
    safe_title = secure_filename(meeting["title"]) or "meeting"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.pdf"'},
    )


@app.route("/upgrade")
@login_required
def upgrade():
    user = db.get_user(session["user_id"])
    if user["plan"] == "paid":
        return redirect(url_for("meetings_list"))

    checkout_url = billing.create_checkout_session(
        user_id=user["id"],
        user_email=user["email"],
        success_url=url_for("upgrade_success", _external=True),
        cancel_url=url_for("meetings_list", _external=True),
    )
    return redirect(checkout_url)


@app.route("/upgrade/success")
@login_required
def upgrade_success():
    # The webhook is the source of truth for actually marking the plan as
    # paid (it fires reliably even if this redirect never happens), so this
    # page just shows a friendly message — it doesn't itself grant access.
    flash("Payment received! Your account will be upgraded within a few seconds.")
    return redirect(url_for("meetings_list"))


@app.route("/billing/portal")
@login_required
def billing_portal():
    user = db.get_user(session["user_id"])
    if not user["stripe_customer_id"]:
        flash("No billing account found yet.")
        return redirect(url_for("meetings_list"))

    portal_url = billing.create_billing_portal_session(
        stripe_customer_id=user["stripe_customer_id"],
        return_url=url_for("meetings_list", _external=True),
    )
    return redirect(portal_url)


@app.route("/billing/webhook", methods=["POST"])
def billing_webhook():
    """
    Stripe calls this directly (not a browser) whenever a billing event
    happens — this is the reliable source of truth for plan changes, not
    the browser redirect after checkout (which can be interrupted).
    """
    import stripe

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = billing.verify_webhook(payload, sig_header)
    except (stripe.SignatureVerificationError, ValueError):
        logger.warning("Rejected webhook request with invalid signature.")
        return "Invalid signature", 400

    event_type = event["type"]
    data = event["data"]["object"].to_dict()

    if event_type == "checkout.session.completed":
        user_id = data.get("client_reference_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        if user_id:
            db.set_stripe_customer_id(user_id, customer_id)
            db.set_user_plan(user_id, "paid", subscription_id)
            logger.info("User %s upgraded to paid plan.", user_id)

    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user = db.get_user_by_stripe_customer_id(customer_id)
        if user:
            db.set_user_plan(user["id"], "free", None)
            logger.info("User %s downgraded to free plan (subscription ended).", user["id"])

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5090))
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
