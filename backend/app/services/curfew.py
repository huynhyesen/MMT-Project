"""Read and evaluate the household curfew against a single clock."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.sqlite import insert

from .. import models, schemas
from .formatters import is_within_curfew


DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


def household_timezone(db):
    schedule = db.get(models.CurfewSchedule, 1)
    return (schedule.timezone if schedule else None) or DEFAULT_TIMEZONE


def curfew_clock(timezone_name):
    return datetime.now(ZoneInfo(timezone_name))


def usage_day_start(timezone_name, day: date | None = None):
    # Store timestamps in SQLite as UTC without an offset.
    zone = ZoneInfo(timezone_name)
    day = day or curfew_clock(timezone_name).date()
    return datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)


def current_curfew(db):
    schedule = db.get(models.CurfewSchedule, 1)
    timezone_name = (schedule.timezone if schedule else None) or DEFAULT_TIMEZONE
    if schedule is None:
        # Existing installations kept these values alongside their time limit categories.
        schedule = db.query(models.TimeLimit).order_by(
            models.TimeLimit.device_id.is_(None).desc(),
            (models.TimeLimit.category == "OVERALL").desc(),
            (models.TimeLimit.category == "LEARNING").desc(),
            models.TimeLimit.id,
        ).first()
    bedtime = (schedule.bedtime if schedule else None) or "22:00"
    wakeup = (schedule.wakeup_time if schedule else None) or "06:00"
    now = curfew_clock(timezone_name)
    return schemas.CurfewResponse(
        bedtime=bedtime.zfill(5),
        wakeup_time=wakeup.zfill(5),
        timezone=timezone_name,
        current_time=now.strftime("%H:%M"),
        server_time=now.astimezone(timezone.utc),
        is_within_curfew=is_within_curfew(bedtime, wakeup, now),
    )


def store_curfew(db, bedtime, wakeup_time, timezone_name=None):
    values = {"bedtime": bedtime.zfill(5), "wakeup_time": wakeup_time.zfill(5)}
    if timezone_name is not None:
        values["timezone"] = timezone_name
    initial_values = {"timezone": DEFAULT_TIMEZONE, **values}
    db.execute(insert(models.CurfewSchedule).values(id=1, **initial_values).on_conflict_do_update(
        index_elements=["id"], set_=values,
    ))
