from datetime import datetime
from types import SimpleNamespace
from unicodedata import normalize

from agent import blocker
from agent.ai_filter.text_analyzer import AITextAnalyzer

from app.services.classification import (
    classify_item,
    extract_target_name
)

from app.services.formatters import (
    format_duration,
    format_remaining,
    is_within_curfew
)


def test_extract_target_name():
    result = extract_target_name(
        "https://www.youtube.com/watch?v=123"
    )

    assert result == "youtube.com"


def test_classify_learning():
    result = classify_item("khanacademy.org")

    assert result["tag"] == "LEARNING"


def test_classify_entertainment():
    result = classify_item("youtube.com")

    assert result["tag"] == "ENTERTAINMENT"


def test_web_classification_matches_whole_domain_labels():
    assert classify_item("m.youtube.com")["tag"] == "ENTERTAINMENT"
    assert classify_item("classroom.google.com")["tag"] == "LEARNING"
    assert classify_item("oj.vnoi.info")["tag"] == "LEARNING"
    assert classify_item("youtube-help.example")["tag"] == "OTHER"
    assert classify_item("youtube.com.example")["tag"] == "OTHER"
    assert classify_item("winword.exe")["tag"] == "LEARNING"


def test_text_rules_warn_for_normalized_keywords_and_skip_partial_words():
    analyzer = AITextAnalyzer()
    assert analyzer.analyze("Alphabet practice in Sussex")["is_safe"]
    assert analyzer.analyze("Blood pressure in a biology lesson")["is_safe"]
    assert analyzer.analyze("Giáo dục giới tính")["is_safe"]
    result = analyzer.analyze(normalize("NFD", "Cá cược trực tuyến"))
    assert result["category"] == "GAMBLING"
    assert result["suggested_action"] == "WARN"


def test_app_blocker_closes_only_matching_executable(monkeypatch):
    terminated = []
    names = ["GAME.EXE", "GameEditor.exe", "winlogon.exe", "python3.12", "cmd.exe"]
    processes = [
        SimpleNamespace(
            info={"pid": index, "name": name, "cmdline": ["Game.exe"]},
            terminate=lambda name=name: terminated.append(name),
            wait=lambda timeout: None,
        )
        for index, name in enumerate(names, start=100)
    ]
    monkeypatch.setattr(blocker.psutil, "process_iter", lambda attrs: processes)
    monkeypatch.setattr(blocker.os, "getpid", lambda: 99)

    assert blocker.kill_blocked_process("game")
    assert not blocker.kill_blocked_process("winlogon.exe")
    assert not blocker.kill_blocked_process("python3.12")
    assert terminated == ["GAME.EXE"]
    assert blocker.matches_app_rule("RobloxPlayerBeta.exe", "roblox")
    assert not blocker.matches_app_rule("NotepadPlusPlus.exe", "notepad")


def test_format_duration():
    assert format_duration(90) == "1 giờ 30 phút"


def test_format_remaining():
    result = format_remaining(120, 90)

    assert result == (30, "Còn 30 phút", False)


def test_curfew_overnight():
    now = datetime(2026, 10, 31, 23, 0)

    assert is_within_curfew(
        "22:00",
        "06:00",
        now
    )


def test_adult_policy_matches_hostname_labels_without_reading_page_paths():
    from agent.web_policy import blocked_hosts_for_agent, is_adult_host, normalize_host

    assert is_adult_host(normalize_host("https://test-p0rn.example/"))
    assert is_adult_host(normalize_host("https://www.18plus.example./"))
    assert classify_item("hihisex.men")["tag"] == "ADULT"
    assert is_adult_host(normalize_host("https://sub.hihisex.men/"))
    assert "hihisex.men" in blocked_hosts_for_agent([])
    assert not is_adult_host(normalize_host("https://hihisex.men.example/"))
    assert not is_adult_host(normalize_host("https://school.example/lesson-about-porn"))
