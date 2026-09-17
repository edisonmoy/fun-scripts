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
    }


def _extract_email_address(sender):
    """Pull a bare email address out of a "Name <email@x.com>" header value."""
    _, address = parseaddr(sender)
    return address


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
    gmail_draft_id = gmail_client.create_draft(
        thread_id, to_address, draft["subject"], draft["body"]
    )

    autonomy_key = "autonomy_keep_warm" if category == "keep_warm" else "autonomy_high_interest"
    if preferences.get(autonomy_key) == "auto_send":
        gmail_client.send_draft(gmail_draft_id)
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
        gmail_draft_id=gmail_draft_id,
        status=status,
        draft_subject=draft.get("subject"),
        draft_body=draft.get("body"),
    )
    counts[category] += 1
    if status == "sent":
        counts["sent"] += 1


def backfill_fit_scores(preferences, counts):
    """Re-score already-triaged rows that predate fit_score (or otherwise
    lack one), so the dashboard's fit meter isn't permanently blank for
    them. Re-classifies against the current thread content but only writes
    back fit_score/rationale - status, draft, and Gmail label are untouched.
    """
    for record in db_client.get_missing_fit_score():
        try:
            thread = gmail_client.get_thread_plaintext(record["gmail_thread_id"])
            classification = classifier.classify(thread, preferences)
            db_client.update_fit_score(
                record["id"], classification.get("fit_score"), classification.get("rationale")
            )
            counts["backfilled"] += 1
        except Exception:
            logger.exception("record_id=%s failed to backfill fit_score", record["id"])
            counts["backfill_failed"] += 1


def process_approved_pending(counts):
    """Send the existing Gmail draft for every dashboard-approved record."""
    for record in db_client.get_approved_pending():
        try:
            gmail_client.send_draft(record["gmail_draft_id"])
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
    backfill_fit_scores(preferences, counts)

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
