from flakeguard.evidence.planted_bundles import PLANTED_BUNDLES


def test_render_all_planted_bundles():
    assert len(PLANTED_BUNDLES) >= 6
    for key, bundle_text in PLANTED_BUNDLES.items():
        assert "=== EVIDENCE BUNDLE FOR TEST:" in bundle_text
        assert "--- 1. RUN STATISTICS ---" in bundle_text
        assert "--- 2. LOG EXCERPT ---" in bundle_text
        assert "--- 3. TEST BODY ---" in bundle_text
        assert "--- 4. CODE & CONTEXT SNIPPETS ---" in bundle_text
        assert "[E1]" in bundle_text
