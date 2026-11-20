
from datetime import datetime


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} phút"

    hours = minutes // 60
    remaining = minutes % 60

    if remaining:
        return f"{hours} giờ {remaining} phút"

    return f"{hours} giờ"


def format_remaining(
    limit_mins: int,
    used_mins: int
) -> tuple[int, str, bool]:

    if limit_mins <= 0:
        return 9999, "Không giới hạn", False

    remaining = limit_mins - used_mins

    if remaining <= 0:
        return 0, "Đã hết giờ (0 phút)", True

    return (
        remaining,
        f"Còn {format_duration(remaining)}",
        False
    )


def is_within_curfew(
    bedtime_str: str,
    wakeup_str: str,
    now: datetime | None = None
) -> bool:

    if not bedtime_str or not wakeup_str:
        return False

    now = now or datetime.now()

    try:
        bedtime = datetime.strptime(
            bedtime_str, "%H:%M"
        ).time()

        wakeup = datetime.strptime(
            wakeup_str, "%H:%M"
        ).time()

        current_time = now.time()

        if bedtime > wakeup:
            return (
                current_time >= bedtime
                or current_time < wakeup
            )

        if bedtime < wakeup:
            return bedtime <= current_time < wakeup

        return False

    except ValueError:
        return False

# dinh dang thoi gian & tinh toan thoi gian su dung