"""Actions planifiées (lot #411) : validation d'une planification et calcul de « est-elle due maintenant ? ». Fonctions pures, testables sans horloge.

Une planification = une machine + une action de la LISTE BLANCHE + des jours de semaine + une heure (`HH:MM`) dans un fuseau horaire. Elle s'exécute une fois par
minute concernée. Un créneau manqué (Kaji arrêté, redémarrage) n'est JAMAIS rattrapé : mieux vaut ne pas démarrer ou arrêter une machine à une heure imprévue.
"""
import re
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, Field, StrictBool, StrictInt

ACTIONS = ("start", "shutdown", "reboot", "stop", "snapshot")        # liste blanche ; `stop` = arrêt forcé (confirmé à la création)
GTYPES = ("qemu", "lxc")
NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$", re.ASCII)
MAX_PER_CONNECTION = 200


def valid_timezone(name: str) -> bool:
    return isinstance(name, str) and len(name) <= 64 and name in available_timezones()


def parse_days(raw) -> list[int] | None:
    """`[0..6]` (0 = lundi) sans doublon, trié ; None si invalide ou vide."""
    if not isinstance(raw, list) or not raw or len(raw) > 7:
        return None
    if any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in raw) or len(set(raw)) != len(raw):
        return None
    return sorted(raw)


def days_to_text(days: list[int]) -> str:
    return ",".join(str(d) for d in days)


def text_to_days(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.isdigit() and 0 <= int(x) <= 6]


class ScheduleBody(BaseModel):
    node: str = Field(max_length=63, pattern=NODE.pattern)
    gtype: str = Field(pattern=r"^(qemu|lxc)$")
    vmid: StrictInt = Field(ge=100, le=999999999)
    action: str = Field(pattern=r"^(start|shutdown|reboot|stop|snapshot)$")
    days: list[Annotated[StrictInt, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    time: str = Field(pattern=HHMM.pattern)
    timezone: str = Field(default="Europe/Paris", max_length=64)
    enabled: StrictBool = True
    confirm: StrictBool = False                                           # exigé pour `stop` (arrêt forcé) et `reboot` répétés : coupure sans arrêt propre


def is_due(days: list[int], hhmm: str, tz: str, now_utc: datetime, last_run_key: str | None) -> tuple[bool, str]:
    """`(due, clé)` : due si, dans le fuseau, le jour de semaine et la minute correspondent ET que cette minute n'a pas déjà été exécutée.
    La clé (`AAAA-MM-JJ HH:MM` locale) est à mémoriser pour ne pas rejouer la même minute."""
    local = now_utc.astimezone(ZoneInfo(tz))
    key = local.strftime("%Y-%m-%d %H:%M")
    return (local.weekday() in days and local.strftime("%H:%M") == hhmm and key != last_run_key), key
