import logging
import os
from datetime import datetime, timezone
from email.utils import parseaddr

import classifier
import config
import db_client
import draft_writer
import gmail_client
import quality_gate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# PRIVACY: fun-scripts is a PUBLIC repo, and GitHub Actions logs/step
# summaries for a public repo are publicly visible to anyone. Recruiter
# emails, sender addresses, subject lines, company/role names, comp
# figures, and draft text are all sensitive. Nothing in this module may
# log or write to GITHUB_STEP_SUMMARY any of that content - only aggregate
# counts and opaque identifiers (Gmail thread ids, DB row ids).


def _new_counts():
    return {
        "candidates": 0,
        "ignore": 0,
        "keep_warm": 0,
        "high_interest": 0,
        "sent": 0,
        "gate_failed": 0,
        "errors": 0,
        "approved_sent": 0,
        "approved_failed": 0,
        "backfilled": 0,
        "backfill_failed": 0,
        "template_backfilled": 0,
        "template_backfill_failed": 0,
    }


def _extract_email_address(sender):
    """Pull a bare email address out of a "Name <email@x.com>" header value."""
    _, address = parseaddr(sender)
    return address


def _should_auto_send(category, fit_score, preferences):
    """Whether a passed-quality-gate draft should be sent immediately.

    The per-category autonomy toggle (draft_only/auto_send) is the primary
    switch. When it's auto_send, an optional fit_score threshold narrows it
    further: keep_warm auto-sends the LOW-fit drafts (clearly generic
    outreach - safe to auto-dismiss) via keep_warm_auto_send_max_fit;
    high_interest auto-sends the HIGH-fit drafts (confidently a strong
    match) via high_interest_auto_send_min_fit. A missing/null threshold
    means no extra gate - the toggle alone decides, as before. A missing
    fit_score (e.g. classifier didn't return one) fails a configured
    threshold closed, i.e. falls back to draft_only for safety.
    """
    if category == "keep_warm":
        autonomy_key, threshold_key, compare = (
            "autonomy_keep_warm",
            "keep_warm_auto_send_max_fit",
            lambda score, threshold: score <= threshold,
        )
    else:
        autonomy_key, threshold_key, compare = (
            "autonomy_high_interest",
            "high_interest_auto_send_min_fit",
            lambda score, threshold: score >= threshold,
        )

    if preferences.get(autonomy_key) != "auto_send":
        return False

    threshold = preferences.get(threshold_key)
    if threshold is None:
        return True
    if fit_score is None:
        return False
    return compare(fit_score, threshold)


def process_candidate_thread(thread_id, preferences, counts):
    """Fetch, classify, and (if warranted) draft a reply for one Gmail
    thread. Mutates `counts` in place. Never logs thread content - only
    the opaque thread_id and category/status outcomes.
    """
    thread = gmail_client.get_thread_plaintext(thread_id)
    classification = classifier.classify(thread, preferences)

    if not classification.get("is_recruiter_outreach"):
        db_client.upsert_triage_record(
            thread_id=thread_id,
            received_at=thread["received_at"],
            sender=thread["sender"],
            subject=thread["subject"],
            category="ignore",
            fit_score=classification.get("fit_score"),
            extracted=classification,
            rationale=classification.get("rationale"),
            gmail_draft_id=None,
            status="ignored",
        )
        counts["ignore"] += 1
        return

    category = classification["category"]
    label_name = config.CATEGORY_LABELS[category]
    label_id = gmail_client.ensure_label(label_name)
    gmail_client.apply_label(thread_id, label_id)

    draft = draft_writer.generate_draft(classification, thread, preferences)
    passed, reason = quality_gate.evaluate(draft.get("body"))

    if not passed:
        # Log only the opaque thread id and the gate's reason string, which
        # by construction (quality_gate.evaluate) never embeds draft body
        # text - only lengths/marker names.
        logger.warning("thread_id=%s quality gate failed: %s", thread_id, reason)
        db_client.upsert_triage_record(
            thread_id=thread_id,
            received_at=thread["received_at"],
            sender=thread["sender"],
            subject=thread["subject"],
            category=category,
            fit_score=classification.get("fit_score"),
            extracted=classification,
            rationale=classification.get("rationale"),
            gmail_draft_id=None,
            status="drafted",
            draft_subject=draft.get("subject"),
            draft_body=draft.get("body"),
        )
        counts[category] += 1
        counts["gate_failed"] += 1
        return

    to_address = _extract_email_address(thread["sender"])

    if _should_auto_send(category, classification.get("fit_score"), preferences):
        gmail_client.send_reply(thread_id, to_address, draft["subject"], draft["body"])
        status = "sent"
    else:
        status = "drafted"

    db_client.upsert_triage_record(
        thread_id=thread_id,
        received_at=thread["received_at"],
        sender=thread["sender"],
        subject=thread["subject"],
        category=category,
        fit_score=classification.get("fit_score"),
        extracted=classification,
        rationale=classification.get("rationale"),
        gmail_draft_id=None,
        status=status,
        draft_subject=draft.get("subject"),
        draft_body=draft.get("body"),
    )
    counts[category] += 1
    if status == "sent":
        counts["sent"] += 1


def backfill_analysis(preferences, counts):
    """Re-analyze already-triaged rows that predate fit_score or the
    required company-description (summary) field, so the dashboard's fit
    meter and blurb aren't permanently blank/stale for them. Re-classifies
    against the current thread content but only writes back
    fit_score/rationale/extracted_json - status, draft, and Gmail label are
    untouched (this is a re-analysis, not a re-triage).
    """
    for record in db_client.get_needs_analysis_backfill():
        try:
            thread = gmail_client.get_thread_plaintext(record["gmail_thread_id"])
            classification = classifier.classify(thread, preferences)
            db_client.update_analysis(
                record["id"],
                classification.get("fit_score"),
                classification.get("rationale"),
                classification,
            )
            counts["backfilled"] += 1
        except Exception:
            logger.exception("record_id=%s failed to backfill analysis", record["id"])
            counts["backfill_failed"] += 1


def backfill_template_drafts(preferences, counts):
    """Regenerate draft_subject/draft_body for not-yet-actioned rows whose
    category now has a keep_warm_template/high_interest_template configured
    but were drafted before that template existed (or before it was last
    edited). Skips rows whose category has no template set - nothing to
    backfill there. Purely deterministic (placeholder substitution, no LLM
    call, no Gmail fetch) since template filling only needs what's already
    stored (sender, subject, extracted_json).
    """
    for record in db_client.get_drafted_records():
        template_key = draft_writer.TEMPLATE_PREFERENCE_KEYS.get(record["category"])
        if not template_key or not preferences.get(template_key):
            continue
        try:
            classification = record["extracted_json"] or {}
            thread = {"sender": record["sender"], "subject": record["subject"]}
            draft = draft_writer.generate_draft(classification, thread, preferences)
            db_client.update_draft_text(record["id"], draft["subject"], draft["body"])
            counts["template_backfilled"] += 1
        except Exception:
            logger.exception("record_id=%s failed to backfill template draft", record["id"])
            counts["template_backfill_failed"] += 1


def process_approved_pending(counts):
    """Send the stored draft text for every dashboard-approved record."""
    for record in db_client.get_approved_pending():
        try:
            to_address = _extract_email_address(record["sender"])
            gmail_client.send_reply(
                record["gmail_thread_id"], to_address, record["draft_subject"], record["draft_body"]
            )
            db_client.mark_sent(record["id"])
            counts["approved_sent"] += 1
        except Exception:
            logger.exception("record_id=%s failed to send approved draft", record["id"])
            counts["approved_failed"] += 1


def write_step_summary(counts):
    """Append a markdown table of aggregate counts to the GitHub Actions run
    summary, if running in Actions. Counts only - see the PRIVACY note at
    the top of this module for why.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        "### Gmail recruiter triage run",
        "",
        "| Metric | Count |",
        "| --- | --- |",
    ]
    for key in (
        "candidates",
        "ignore",
        "keep_warm",
        "high_interest",
        "sent",
        "gate_failed",
        "errors",
        "approved_sent",
        "approved_failed",
        "backfilled",
        "backfill_failed",
        "template_backfilled",
        "template_backfill_failed",
    ):
        lines.append(f"| {key} | {counts.get(key, 0)} |")
    lines.append("")

    with open(summary_path, "a") as f:
        f.write("\n".join(lines) + "\n")


def main():
    preferences = db_client.get_preferences()
    last_run_at = db_client.get_last_run_at()
    run_started_at = datetime.now(timezone.utc)

    thread_ids = gmail_client.search_candidate_threads(config.GMAIL_SEARCH_QUERY, last_run_at)

    counts = _new_counts()

    for thread_id in thread_ids:
        if db_client.is_thread_processed(thread_id):
            continue
        counts["candidates"] += 1
        try:
            process_candidate_thread(thread_id, preferences, counts)
        except Exception:
            # Log only the thread id and exception type/message - never
            # re-raise content pulled from the email into the log line.
            logger.exception("thread_id=%s failed during triage", thread_id)
            counts["errors"] += 1

    process_approved_pending(counts)
    backfill_analysis(preferences, counts)
    backfill_template_drafts(preferences, counts)

    db_client.set_last_run_at(run_started_at)

    logger.info(
        "processed %d candidate threads: %d keep_warm, %d high_interest, %d ignored, "
        "%d errors",
        counts["candidates"],
        counts["keep_warm"],
        counts["high_interest"],
        counts["ignore"],
        counts["errors"],
    )
    write_step_summary(counts)


if __name__ == "__main__":
    main()
