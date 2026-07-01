# Model Card

## Назначение

Direction-conditional оценка исходов `TP / SL / TIMEOUT` для LONG и SHORT сценариев. `NO TRADE` остаётся policy decision, а не классом модели.

## Данные и время

Features строятся только по confirmed hourly candles. Decision-time и label-end semantics разделены; temporal split purged по фактическому label horizon. Inference версии 1.8.25 разделяет market cutoff и availability cutoff.

## Activation

Candidate artifact immutable, снабжается hash/metadata и сравнивается с incumbent на совместимом final holdout. Auto-activation допускается только после absolute и relative ML/policy gates. Ошибка candidate не деактивирует incumbent.

## Не доказано

Зелёные тесты и корректная реализация не доказывают устойчивую доходность. Необходимы OOS/forward evidence, контроль regime/drift и реалистичная оценка исполнения.
