# PulseKeeper Communication Cadence

PulseKeeper should feel useful without becoming noisy. The default stance is: no proactive nudges unless configured by the user.

## Daily check-in

Daily check-in messages are optional and only if the user opted in.

Example:

```text
Короткий чек-ин: вес / сон / тренировка / самочувствие — что-нибудь записать?
```

Rules:
- keep it short;
- invite one lightweight log;
- do not imply the user failed if they skip it.

## Weekly review

Weekly review is the default useful cadence when summaries are requested or scheduled by the user.

Example:

```text
Еженедельная сводка готова:
• Вес: 4 записи, диапазон 82.1–82.8 кг
• Тренировки: 3 события
• Сон: мало данных
• Симптомы: головная боль отмечалась 2 раза вечером

Один возможный следующий шаг: если хочешь, на следующей неделе будем отдельно отмечать сон и головную боль.
```

Rules:
- summarize observed patterns and data gaps;
- avoid diagnosis or treatment advice;
- end with at most one small next action.

## Missed logging nudge

Missed logging nudge messages are only if the user opted in. They must be no guilt, no shame, and no pressure.

Good:

```text
Давно ничего не записывали. Если хочешь, можешь просто написать вес, сон или самочувствие одной фразой.
```

Bad:

```text
Ты пропустил дневник. Регулярность очень важна...
```

Rules:
- reminders are useful and short;
- no guilt or shame language;
- no proactive nudges unless configured.
