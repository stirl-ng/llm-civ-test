"""Tests for TurnJournal — no game, no orchestrator required."""
import json
import tempfile
from pathlib import Path

import pytest

from agent_runtime.memory.journal import TurnJournal, TurnRecap


@pytest.fixture
def journal(tmp_path):
    j = TurnJournal(tmp_path / "journal.json")
    j.set_current_player("test-model")
    return j


def test_record_and_get_recaps(journal):
    journal.record_turn(game_id=1, turn=3, text="Scouted north. Planning to settle river.")
    recaps = journal.get_recaps(game_id=1)
    assert len(recaps) == 1
    assert recaps[0].turn == 3
    assert "Scouted north" in recaps[0].text


def test_upsert_same_turn(journal):
    journal.record_turn(game_id=1, turn=5, text="First write.")
    journal.record_turn(game_id=1, turn=5, text="Overwritten.")
    recaps = journal.get_recaps(game_id=1)
    assert len(recaps) == 1
    assert recaps[0].text == "Overwritten."


def test_recaps_sorted_by_turn(journal):
    journal.record_turn(game_id=1, turn=10, text="Ten.")
    journal.record_turn(game_id=1, turn=2, text="Two.")
    journal.record_turn(game_id=1, turn=7, text="Seven.")
    recaps = journal.get_recaps(game_id=1, limit=10)
    assert [r.turn for r in recaps] == [2, 7, 10]


def test_get_recaps_limit(journal):
    for t in range(10):
        journal.record_turn(game_id=1, turn=t, text=f"Turn {t}.")
    recaps = journal.get_recaps(game_id=1, limit=3)
    assert len(recaps) == 3
    assert [r.turn for r in recaps] == [7, 8, 9]


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "journal.json"
    j1 = TurnJournal(path)
    j1.set_current_player("test-model")
    j1.record_turn(game_id=42, turn=5, text="Persisted.")
    j1.update_narrative(game_id=42, current_strategy="Science victory")

    j2 = TurnJournal(path)
    recaps = j2.get_recaps(game_id=42)
    assert len(recaps) == 1
    assert recaps[0].text == "Persisted."
    narrative = j2.get_or_create_narrative(42)
    assert narrative.current_strategy == "Science victory"


def test_build_context_summary_includes_recap_text(journal):
    journal.record_turn(game_id=1, turn=4, text="Founded second city near the river.")
    summary = journal.build_context_summary(game_id=1, current_turn=5)
    assert "Founded second city" in summary


def test_lessons_round_trip(tmp_path):
    path = tmp_path / "journal.json"
    j1 = TurnJournal(path)
    j1.set_current_player("test-model")
    j1.record_lesson(content="Coastal cities need naval defense.", game_id=1, turn=20, category="military")

    j2 = TurnJournal(path)
    j2.set_current_player("test-model")
    lessons = j2.get_lessons(category="military")
    assert len(lessons) == 1
    assert "naval" in lessons[0].content
