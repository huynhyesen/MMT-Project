from datetime import datetime

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