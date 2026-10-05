import pytest

from flakeguard.eval.metrics import (
    bootstrap_ci,
    compute_confusion_matrix,
    compute_false_quarantine_rate,
    compute_precision_recall_f1,
    compute_root_cause_accuracy,
)


@pytest.fixture
def tiny_handmade_example():
    """Tiny handmade example dataset with 6 items.

    Item 1: actual="flaky", pred="flaky" (TP)
    Item 2: actual="flaky", pred="flaky" (TP)
    Item 3: actual="flaky", pred="stable" (FN)
    Item 4: actual="stable", pred="flaky" (FP)
    Item 5: actual="real", pred="flaky" (FP, real failure mislabeled flaky -> false quarantine)
    Item 6: actual="real", pred="real" (TN for flaky, true positive for real failure)
    """
    y_true = ["flaky", "flaky", "flaky", "stable", "real", "real"]
    y_pred = ["flaky", "flaky", "stable", "flaky", "flaky", "real"]
    rc_true = [
        "order_dep",
        "shared_state",
        "timing",
        "none",
        "none",
        "none",
    ]
    rc_pred = [
        "order_dep",
        "timing",
        "none",
        "shared_state",
        "none",
        "none",
    ]

    return {
        "y_true": y_true,
        "y_pred": y_pred,
        "rc_true": rc_true,
        "rc_pred": rc_pred,
    }


def test_precision_recall_f1(tiny_handmade_example):
    y_true = tiny_handmade_example["y_true"]
    y_pred = tiny_handmade_example["y_pred"]

    metrics = compute_precision_recall_f1(y_true, y_pred, pos_label="flaky")

    # TP = 2, FP = 2 (stable->flaky, real->flaky), FN = 1 (flaky->stable)
    assert metrics["tp"] == 2
    assert metrics["fp"] == 2
    assert metrics["fn"] == 1

    # Precision = 2 / 4 = 0.5
    assert metrics["precision"] == pytest.approx(0.5)

    # Recall = 2 / 3 ≈ 0.6667
    assert metrics["recall"] == pytest.approx(2 / 3)

    # F1 = 2 * (0.5 * 2/3) / (0.5 + 2/3) = 4 / 7 ≈ 0.5714
    assert metrics["f1"] == pytest.approx(4 / 7)


def test_false_quarantine_rate(tiny_handmade_example):
    y_true = tiny_handmade_example["y_true"]
    y_pred = tiny_handmade_example["y_pred"]

    fq_rate = compute_false_quarantine_rate(
        y_true, y_pred, real_label="real", flaky_label="flaky"
    )

    # Total real failures = 2 (items 5 & 6)
    # Real failures labeled flaky = 1 (item 5)
    # False quarantine rate = 1 / 2 = 0.5
    assert fq_rate == pytest.approx(0.5)


def test_confusion_matrix(tiny_handmade_example):
    y_true = tiny_handmade_example["y_true"]
    y_pred = tiny_handmade_example["y_pred"]

    cm = compute_confusion_matrix(
        y_true, y_pred, labels=["flaky", "real", "stable"]
    )

    assert cm["flaky"]["flaky"] == 2
    assert cm["flaky"]["stable"] == 1
    assert cm["flaky"]["real"] == 0

    assert cm["real"]["flaky"] == 1
    assert cm["real"]["real"] == 1

    assert cm["stable"]["flaky"] == 1
    assert cm["stable"]["stable"] == 0


def test_root_cause_accuracy(tiny_handmade_example):
    rc_true = tiny_handmade_example["rc_true"]
    rc_pred = tiny_handmade_example["rc_pred"]

    acc = compute_root_cause_accuracy(rc_true, rc_pred)

    # Correct matches: index 0 (order_dep), 4 (none), 5 (none) -> 3 out of 6
    assert acc == pytest.approx(3 / 6)


def test_bootstrap_ci_hand_example(tiny_handmade_example):
    dataset = [
        {"true": t, "pred": p}
        for t, p in zip(
            tiny_handmade_example["y_true"], tiny_handmade_example["y_pred"]
        )
    ]

    def metric_f1(sample):
        yt = [s["true"] for s in sample]
        yp = [s["pred"] for s in sample]
        return compute_precision_recall_f1(yt, yp, pos_label="flaky")["f1"]

    ci_res = bootstrap_ci(metric_f1, dataset, n_bootstraps=500, seed=42)

    assert "mean" in ci_res
    assert "ci_lower" in ci_res
    assert "ci_upper" in ci_res
    assert 0.0 <= ci_res["ci_lower"] <= ci_res["mean"] <= ci_res["ci_upper"] <= 1.0
