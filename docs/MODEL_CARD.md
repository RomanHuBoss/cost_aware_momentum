# Model Card

## Назначение

Direction-conditional оценка исходов `TP / SL / TIMEOUT` для LONG и SHORT сценариев. `NO TRADE` остаётся policy decision, а не классом модели.

## Данные и время

Features строятся только по confirmed hourly candles. Decision-time и label-end semantics разделены; temporal split purged по фактическому label horizon. Inference разделяет market cutoff и availability cutoff. Версия 1.8.26 дополнительно запрещает auto-activation при отрицательном минимальном realized mean R или profit factor ниже 1.

## Activation

Candidate artifact immutable, снабжается hash/metadata и сравнивается с incumbent на совместимом final holdout. Auto-activation допускается только после absolute и relative ML/policy gates. При включенной auto-activation абсолютный порог realized mean R не может быть отрицательным, а минимальный profit factor не может быть ниже 1. Ошибка candidate не деактивирует incumbent.

## Не доказано

Зелёные тесты и корректная реализация не доказывают устойчивую доходность. Необходимы OOS/forward evidence, контроль regime/drift и реалистичная оценка исполнения.
