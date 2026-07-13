"""Tests for the andon summon channel."""

from src.summon import EmailSummoner, LogSummoner, Summoner


class TestLogSummoner:
    def test_records_summons(self):
        s = LogSummoner()
        assert isinstance(s, Summoner)
        s.summon({"event": "halt", "artifact": "EEK:PRD"})
        assert s.summons == [{"event": "halt", "artifact": "EEK:PRD"}]


class TestEmailSummoner:
    def test_formats_subject_and_body_and_sends(self):
        sent = {}
        def send(subject, body):
            sent["subject"] = subject
            sent["body"] = body
        EmailSummoner(send, to="todd@example.com").summon(
            {"event": "trip", "severity": "FAULTED", "artifact": "EEK:SAD", "reason": "breach"}
        )
        assert "andon" in sent["subject"] and "FAULTED" in sent["subject"]
        assert "EEK:SAD" in sent["subject"]
        assert "todd@example.com" in sent["body"]
        assert "reason: breach" in sent["body"]

    def test_no_to_omits_recipient_line(self):
        sent = {}
        EmailSummoner(lambda s, b: sent.update(body=b)).summon({"event": "halt"})
        assert not sent["body"].startswith("To:")
