from inventory.report import Report


def test_report_total():
    report = Report()
    total = report.total("sku-1")
    assert total == 0


def test_report_empty():
    assert Report().title() == "Report"
