from unittest.mock import MagicMock

import main


def _counts():
    return main._new_counts()


def _thread(sender="Jane <jane@co.com>", subject="Role", body="..."):
    return {"sender": sender, "subject": subject, "body": body, "received_at": None}


def test_should_auto_send_false_when_autonomy_is_draft_only():
    prefs = {"autonomy_keep_warm": "draft_only"}
    assert main._should_auto_send("keep_warm", 10, prefs) is False


def test_should_auto_send_true_with_auto_send_and_no_threshold():
    prefs = {"autonomy_keep_warm": "auto_send"}
    assert main._should_auto_send("keep_warm", 95, prefs) is True


def test_should_auto_send_keep_warm_respects_max_fit_threshold():
    prefs = {"autonomy_keep_warm": "auto_send", "keep_warm_auto_send_max_fit": 30}
    assert main._should_auto_send("keep_warm", 30, prefs) is True
    assert main._should_auto_send("keep_warm", 31, prefs) is False


def test_should_auto_send_high_interest_respects_min_fit_threshold():
    prefs = {"autonomy_high_interest": "auto_send", "high_interest_auto_send_min_fit": 80}
    assert main._should_auto_send("high_interest", 80, prefs) is True
    assert main._should_auto_send("high_interest", 79, prefs) is False


def test_should_auto_send_missing_fit_score_fails_closed_with_threshold():
    prefs = {"autonomy_keep_warm": "auto_send", "keep_warm_auto_send_max_fit": 30}
    assert main._should_auto_send("keep_warm", None, prefs) is False


def test_process_candidate_thread_ignores_non_recruiter_outreach(monkeypatch):
    monkeypatch.setattr(main.gmail_client, "get_thread_plaintext", lambda tid: _thread())
    monkeypatch.setattr(
        main.classifier,
        "classify",
        lambda thread, prefs: {
            "is_recruiter_outreach": False,
            "category": "ignore",
            "rationale": "newsletter, not recruiter outreach",
        },
    )
    upsert_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "upsert_triage_record", upsert_mock)
    send_reply_mock = MagicMock()
    monkeypatch.setattr(main.gmail_client, "send_reply", send_reply_mock)

    counts = _counts()
    main.process_candidate_thread("thread-1", {}, counts)

    assert counts["ignore"] == 1
    send_reply_mock.assert_not_called()
    upsert_mock.assert_called_once()
    assert upsert_mock.call_args.kwargs["status"] == "ignored"
    assert upsert_mock.call_args.kwargs["category"] == "ignore"


def test_process_candidate_thread_auto_sends_when_configured(monkeypatch):
    monkeypatch.setattr(main.gmail_client, "get_thread_plaintext", lambda tid: _thread())
    monkeypatch.setattr(
        main.classifier,
        "classify",
        lambda thread, prefs: {
            "is_recruiter_outreach": True,
            "category": "keep_warm",
            "company": "Co",
            "role": "Eng",
            "rationale": "generic recruiter outreach",
        },
    )
    monkeypatch.setattr(
        main.draft_writer,
        "generate_draft",
        lambda cls, thread, prefs: {"subject": "Re: Role", "body": "A" * 60},
    )
    monkeypatch.setattr(main.gmail_client, "ensure_label", lambda name: "label-123")
    monkeypatch.setattr(main.gmail_client, "apply_label", MagicMock())
    send_mock = MagicMock()
    monkeypatch.setattr(main.gmail_client, "send_reply", send_mock)
    upsert_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "upsert_triage_record", upsert_mock)

    preferences = {"autonomy_keep_warm": "auto_send", "autonomy_high_interest": "draft_only"}
    counts = _counts()
    main.process_candidate_thread("thread-2", preferences, counts)

    send_mock.assert_called_once_with("thread-2", "jane@co.com", "Re: Role", "A" * 60)
    assert upsert_mock.call_args.kwargs["status"] == "sent"
    assert upsert_mock.call_args.kwargs["gmail_draft_id"] is None
    assert counts["sent"] == 1
    assert counts["keep_warm"] == 1


def test_process_candidate_thread_draft_only_when_not_auto_send(monkeypatch):
    monkeypatch.setattr(main.gmail_client, "get_thread_plaintext", lambda tid: _thread())
    monkeypatch.setattr(
        main.classifier,
        "classify",
        lambda thread, prefs: {
            "is_recruiter_outreach": True,
            "category": "high_interest",
            "company": "Co",
            "role": "Eng",
            "rationale": "matches target areas",
        },
    )
    monkeypatch.setattr(
        main.draft_writer,
        "generate_draft",
        lambda cls, thread, prefs: {"subject": "Re: Role", "body": "A" * 60},
    )
    monkeypatch.setattr(main.gmail_client, "ensure_label", lambda name: "label-123")
    monkeypatch.setattr(main.gmail_client, "apply_label", MagicMock())
    send_mock = MagicMock()
    monkeypatch.setattr(main.gmail_client, "send_reply", send_mock)
    upsert_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "upsert_triage_record", upsert_mock)

    preferences = {"autonomy_keep_warm": "draft_only", "autonomy_high_interest": "draft_only"}
    counts = _counts()
    main.process_candidate_thread("thread-3", preferences, counts)

    send_mock.assert_not_called()
    assert upsert_mock.call_args.kwargs["status"] == "drafted"
    assert upsert_mock.call_args.kwargs["gmail_draft_id"] is None
    assert counts["high_interest"] == 1
    assert counts["sent"] == 0


def test_process_candidate_thread_quality_gate_failure_never_sends(monkeypatch):
    monkeypatch.setattr(main.gmail_client, "get_thread_plaintext", lambda tid: _thread())
    monkeypatch.setattr(
        main.classifier,
        "classify",
        lambda thread, prefs: {
            "is_recruiter_outreach": True,
            "category": "keep_warm",
            "company": "Co",
            "role": "Eng",
            "rationale": "generic recruiter outreach",
        },
    )
    monkeypatch.setattr(
        main.draft_writer,
        "generate_draft",
        lambda cls, thread, prefs: {"subject": "Re:", "body": "short"},
    )
    monkeypatch.setattr(main.gmail_client, "ensure_label", lambda name: "label-123")
    monkeypatch.setattr(main.gmail_client, "apply_label", MagicMock())
    send_mock = MagicMock()
    monkeypatch.setattr(main.gmail_client, "send_reply", send_mock)
    upsert_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "upsert_triage_record", upsert_mock)

    # Even with auto_send configured, a gate failure must never send.
    preferences = {"autonomy_keep_warm": "auto_send", "autonomy_high_interest": "auto_send"}
    counts = _counts()
    main.process_candidate_thread("thread-4", preferences, counts)

    send_mock.assert_not_called()
    assert upsert_mock.call_args.kwargs["status"] == "drafted"
    assert upsert_mock.call_args.kwargs["gmail_draft_id"] is None
    assert counts["gate_failed"] == 1
    assert counts["keep_warm"] == 1


def test_backfill_analysis_updates_missing_rows(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_needs_analysis_backfill",
        lambda: [{"id": 1, "gmail_thread_id": "thread-1"}],
    )
    monkeypatch.setattr(main.gmail_client, "get_thread_plaintext", lambda tid: _thread())
    classification = {
        "fit_score": 62,
        "rationale": "updated rationale",
        "summary": "Acme builds fraud detection tooling for banks",
    }
    monkeypatch.setattr(main.classifier, "classify", lambda thread, prefs: classification)
    update_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "update_analysis", update_mock)

    counts = _counts()
    main.backfill_analysis({}, counts)

    update_mock.assert_called_once_with(1, 62, "updated rationale", classification)
    assert counts["backfilled"] == 1
    assert counts["backfill_failed"] == 0


def test_backfill_analysis_handles_failure(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_needs_analysis_backfill",
        lambda: [{"id": 1, "gmail_thread_id": "thread-1"}],
    )
    monkeypatch.setattr(
        main.gmail_client,
        "get_thread_plaintext",
        MagicMock(side_effect=Exception("boom")),
    )
    update_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "update_analysis", update_mock)

    counts = _counts()
    main.backfill_analysis({}, counts)

    update_mock.assert_not_called()
    assert counts["backfilled"] == 0
    assert counts["backfill_failed"] == 1


def test_process_approved_pending_sends_and_marks_sent(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_approved_pending",
        lambda: [
            {
                "id": 1,
                "gmail_thread_id": "t1",
                "sender": "Jane <jane@co.com>",
                "draft_subject": "Re: Role",
                "draft_body": "Thanks.",
            },
            {
                "id": 2,
                "gmail_thread_id": "t2",
                "sender": "Sam <sam@co.com>",
                "draft_subject": "Re: Role 2",
                "draft_body": "Thanks again.",
            },
        ],
    )
    send_mock = MagicMock()
    monkeypatch.setattr(main.gmail_client, "send_reply", send_mock)
    mark_sent_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "mark_sent", mark_sent_mock)

    counts = _counts()
    main.process_approved_pending(counts)

    assert send_mock.call_count == 2
    send_mock.assert_any_call("t1", "jane@co.com", "Re: Role", "Thanks.")
    assert mark_sent_mock.call_count == 2
    assert counts["approved_sent"] == 2
    assert counts["approved_failed"] == 0


def test_process_approved_pending_handles_send_failure(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_approved_pending",
        lambda: [
            {
                "id": 1,
                "gmail_thread_id": "t1",
                "sender": "jane@co.com",
                "draft_subject": "Re: Role",
                "draft_body": "Thanks.",
            }
        ],
    )
    monkeypatch.setattr(
        main.gmail_client, "send_reply", MagicMock(side_effect=Exception("boom"))
    )
    mark_sent_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "mark_sent", mark_sent_mock)

    counts = _counts()
    main.process_approved_pending(counts)

    mark_sent_mock.assert_not_called()
    assert counts["approved_failed"] == 1
    assert counts["approved_sent"] == 0


def test_backfill_template_drafts_skips_categories_without_template(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_drafted_records",
        lambda: [{"id": 1, "category": "keep_warm", "sender": "a@b.com", "subject": "S"}],
    )
    generate_mock = MagicMock()
    monkeypatch.setattr(main.draft_writer, "generate_draft", generate_mock)
    update_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "update_draft_text", update_mock)

    counts = _counts()
    main.backfill_template_drafts({}, counts)

    generate_mock.assert_not_called()
    update_mock.assert_not_called()
    assert counts["template_backfilled"] == 0


def test_backfill_template_drafts_regenerates_when_template_set(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_drafted_records",
        lambda: [
            {
                "id": 1,
                "category": "keep_warm",
                "sender": "Dan <dan@co.com>",
                "subject": "S",
                "extracted_json": {"company": "Acme"},
            }
        ],
    )
    monkeypatch.setattr(
        main.draft_writer,
        "generate_draft",
        lambda cls, thread, prefs: {"subject": "Re: S", "body": "Hi Dan."},
    )
    update_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "update_draft_text", update_mock)

    preferences = {"keep_warm_template": "Hi <name>."}
    counts = _counts()
    main.backfill_template_drafts(preferences, counts)

    update_mock.assert_called_once_with(1, "Re: S", "Hi Dan.")
    assert counts["template_backfilled"] == 1
    assert counts["template_backfill_failed"] == 0


def test_backfill_template_drafts_handles_failure(monkeypatch):
    monkeypatch.setattr(
        main.db_client,
        "get_drafted_records",
        lambda: [
            {
                "id": 1,
                "category": "keep_warm",
                "sender": "a@b.com",
                "subject": "S",
                "extracted_json": {},
            }
        ],
    )
    monkeypatch.setattr(
        main.draft_writer, "generate_draft", MagicMock(side_effect=Exception("boom"))
    )
    update_mock = MagicMock()
    monkeypatch.setattr(main.db_client, "update_draft_text", update_mock)

    preferences = {"keep_warm_template": "Hi <name>."}
    counts = _counts()
    main.backfill_template_drafts(preferences, counts)

    update_mock.assert_not_called()
    assert counts["template_backfilled"] == 0
    assert counts["template_backfill_failed"] == 1
