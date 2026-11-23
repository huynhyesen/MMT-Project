"""Read and evaluate the household curfew against a single clock."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.sqlite import insert

from .. import models, schemas
from .formatters import is_within_curfew


def curfew_clock(timezone_name):
    if timezone_name:
        return datetime.now(ZoneInfo(timezone_name))
    return datetime.now().astimezone()


def current_curfew(db):
    schedule = db.get(models.CurfewSchedule, 1)
    timezone_name = schedule.timezone if schedule else None
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
        is_within_curfew=is_within_curfew(bedtime, wakeup, now),
    )


def store_curfew(db, bedtime, wakeup_time, timezone_name=None):
    values = {"bedtime": bedtime.zfill(5), "wakeup_time": wakeup_time.zfill(5)}
    if timezone_name is not None:
        values["timezone"] = timezone_name
    db.execute(insert(models.CurfewSchedule).values(id=1, **values).on_conflict_do_update(
        index_elements=["id"], set_=values,
    ))
