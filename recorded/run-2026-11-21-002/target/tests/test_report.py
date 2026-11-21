from inventory.report import Report


def test_report_total():
    # Order-dependent victim: fails if test_cache_warm ran before it.
    report = Report()
    total = report.total("sku-1")
    assert total == 0


def test_report_title():
    assert Report().title() == "Report"
