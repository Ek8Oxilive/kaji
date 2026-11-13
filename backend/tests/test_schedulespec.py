from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app import schedulespec as S

OK = {"node": "enzo", "gtype": "qemu", "vmid": 115, "action": "start", "days": [0, 1], "time": "07:30"}


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_valid_body_and_defaults():
    b = S.ScheduleBody(**OK)
    assert b.timezone == "Europe/Paris" and b.enabled is True and b.confirm is False


@pytest.mark.parametrize("over", [
    {"node": "a b"}, {"node": "-x"}, {"node": "x" * 70}, {"gtype": "vm"}, {"gtype": "QEMU"}, {"vmid": 99}, {"vmid": "115"}, {"vmid": True}, {"vmid": 1.5},
    {"action": "delete"}, {"action": "migrate"}, {"action": "Start"}, {"action": "start\n"}, {"days": []}, {"days": [7]}, {"days": [-1]}, {"days": ["1"]}, {"days": [True]},
    {"days": [0] * 8}, {"time": "24:00"}, {"time": "7:30"}, {"time": "07:60"}, {"time": "07:30\n"}, {"time": "０７:３０"}, {"time": ""}, {"enabled": "oui"}, {"confirm": 1},
])
def test_invalid_bodies_are_refused(over):
    with pytest.raises(ValidationError):
        S.ScheduleBody(**{**OK, **over})


def test_timezones_and_days_helpers():
    assert S.valid_timezone("Europe/Paris") and S.valid_timezone("UTC") and not S.valid_timezone("Mars/Base") and not S.valid_timezone("../etc") and not S.valid_timezone(None)
    assert S.parse_days([3, 1]) == [1, 3] and S.parse_days([]) is None and S.parse_days([1, 1]) is None and S.parse_days([7]) is None and S.parse_days("1") is None
    assert S.text_to_days(S.days_to_text([0, 6])) == [0, 6] and S.text_to_days("1,x,9,2") == [1, 2]


def test_due_in_the_schedules_time_zone_not_in_utc():
    # lundi 2026-11-16, 07:30 à Paris (UTC+1 en novembre) = 06:30 UTC
    assert S.is_due([0], "07:30", "Europe/Paris", utc(2026, 11, 16, 6, 30), None) == (True, "2026-11-16 07:30")
    assert S.is_due([0], "07:30", "Europe/Paris", utc(2026, 11, 16, 7, 30), None)[0] is False            # 07:30 UTC = 08:30 à Paris
    assert S.is_due([0], "07:30", "UTC", utc(2026, 11, 16, 7, 30), None)[0] is True


def test_due_only_on_the_right_weekday_and_minute():
    assert S.is_due([1], "07:30", "UTC", utc(2026, 11, 16, 7, 30), None)[0] is False                   # lundi, pas mardi
    assert S.is_due([0], "07:30", "UTC", utc(2026, 11, 16, 7, 31), None)[0] is False
    assert S.is_due([0], "07:30", "UTC", utc(2026, 11, 16, 7, 29), None)[0] is False


def test_the_same_minute_is_never_replayed():
    due, key = S.is_due([0], "07:30", "UTC", utc(2026, 11, 16, 7, 30), None)
    assert due and S.is_due([0], "07:30", "UTC", utc(2026, 11, 16, 7, 30), key)[0] is False
    assert S.is_due([0], "07:30", "UTC", utc(2026, 11, 23, 7, 30), key)[0] is True                       # la semaine suivante, oui


def test_next_run_is_the_next_matching_slot_in_utc():
    # dimanche 2026-11-15 12:00 UTC ; prochain lundi 07:30 à Paris = 06:30 UTC le 16
    assert S.next_run([0], "07:30", "Europe/Paris", utc(2026, 11, 15, 12, 0)) == utc(2026, 11, 16, 6, 30)
    assert S.next_run([0], "07:30", "Europe/Paris", utc(2026, 11, 16, 6, 30)) == utc(2026, 11, 23, 6, 30)       # le créneau en cours n'est pas « à venir »
    assert S.next_run([0], "07:30", "Europe/Paris", utc(2026, 11, 16, 6, 29)) == utc(2026, 11, 16, 6, 30)
    assert S.next_run([0, 3], "07:30", "UTC", utc(2026, 11, 16, 8, 0)) == utc(2026, 11, 19, 7, 30)               # jeudi


def test_next_run_skips_the_hour_that_does_not_exist():
    # dimanche 29 mars 2026 à Paris : 02:30 n'existe pas ; le prochain dimanche 02:30 est le 5 avril
    assert S.next_run([6], "02:30", "Europe/Paris", utc(2026, 3, 28, 12, 0)) == utc(2026, 4, 5, 0, 30)


def test_daylight_saving_change_day():
    # passage à l'heure d'été 2026 à Paris : dimanche 29 mars, 02:00 -> 03:00 ; 02:30 n'existe pas ce jour-là (jamais exécuté), 03:30 existe
    assert S.is_due([6], "02:30", "Europe/Paris", utc(2026, 3, 29, 1, 30), None)[0] is False
    assert S.is_due([6], "03:30", "Europe/Paris", utc(2026, 3, 29, 1, 30), None)[0] is True
