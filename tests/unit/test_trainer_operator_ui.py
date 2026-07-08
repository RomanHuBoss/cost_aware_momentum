from pathlib import Path


def test_operator_ui_exposes_trainer_status_dialog_and_safe_controls() -> None:
    root = Path(__file__).resolve().parents[2]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "web" / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="trainer-button"' in html
    assert 'id="trainer-dialog"' in html
    assert 'id="trainer-check-button"' in html
    assert 'id="trainer-recover-button"' in html
    assert "/api/v1/admin/trainer-control" in javascript
    assert "not_enough_new_labeled_time" in javascript
    assert "not_enough_history_for_bootstrap" in javascript
    assert "quality_gate_failed_waiting_for_new_data" in javascript
    assert "training_deferred_waiting_for_new_data" in javascript
    assert "no_direction_specific_barrier_labels" in javascript
    assert "last_training_failed_waiting_for_retry" in javascript
    assert "effective_wait_reason" in javascript
