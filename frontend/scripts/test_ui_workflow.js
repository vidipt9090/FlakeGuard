import puppeteer from 'puppeteer-core';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE_URL = 'http://127.0.0.1:5173';

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function runTests() {
  console.log('--- FlakeGuard Full UI & Workflow Automated Verification ---');
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1400,900'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 900 });

  const errors = [];
  page.on('pageerror', (err) => {
    console.error('[PAGE ERROR]', err.message);
    errors.push(err.message);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.error('[CONSOLE ERROR]', msg.text());
    }
  });

  const results = [];
  function assert(name, condition, details = '') {
    if (condition) {
      console.log(`  [PASS] ${name} ${details}`);
      results.push({ name, pass: true, details });
    } else {
      console.error(`  [FAIL] ${name} ${details}`);
      results.push({ name, pass: false, details });
    }
  }

  try {
    // 1. Load Page
    console.log('\n1. Navigating to FlakeGuard Frontend...');
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: 15000 });
    const pageTitle = await page.title();
    assert('Page loaded successfully', pageTitle.length > 0, `Title: "${pageTitle}"`);

    // Verify top bar and brand
    const brandName = await page.$eval('.brand-name', (el) => el.textContent.trim());
    assert('Brand header', brandName === 'FlakeGuard', `Found: "${brandName}"`);

    // Verify 4 top navigation tabs
    const tabs = await page.$$eval('.nav-tab-btn', (els) => els.map((e) => e.textContent.trim()));
    assert('Top Navigation has 4 tabs', tabs.length === 4, `Tabs: ${JSON.stringify(tabs)}`);

    // 2. Start View / Triage Inputs and Source Selection Cards
    console.log('\n2. Testing Start View Inputs & Source Cards...');
    const heroTitle = await page.$eval('.hero-headline', (el) => el.textContent.trim());
    assert('Start View Headline', heroTitle === "Find the tests you can't trust.");

    // Source Cards
    const sourceCards = await page.$$('.source-card');
    assert('4 Source Selection Cards present', sourceCards.length === 4);

    // Click "My GitHub repo"
    await sourceCards[0].click();
    await delay(200);
    let repoVal = await page.$eval('.repo-input', (el) => el.value);
    assert('Source Card 1 (My GitHub repo) clicked', repoVal.includes('github.com/owner/repository'), `Value: ${repoVal}`);

    // Click "Demo repo"
    await sourceCards[1].click();
    await delay(200);
    repoVal = await page.$eval('.repo-input', (el) => el.value);
    assert('Source Card 2 (Demo repo) clicked', repoVal === 'vidipt9090/flakeguard-demo', `Value: ${repoVal}`);

    // Click "cachetools"
    await sourceCards[2].click();
    await delay(200);
    repoVal = await page.$eval('.repo-input', (el) => el.value);
    assert('Source Card 3 (cachetools) clicked', repoVal === 'tkem/cachetools', `Value: ${repoVal}`);

    // Click "Synthetic benchmark"
    await sourceCards[3].click();
    await delay(200);
    repoVal = await page.$eval('.repo-input', (el) => el.value);
    assert('Source Card 4 (Synthetic benchmark) clicked', repoVal === 'synthetic', `Value: ${repoVal}`);

    // Switch back to Demo repo
    await sourceCards[1].click();
    await delay(200);

    // Test text input change
    await page.focus('.repo-input');
    await page.keyboard.down('Control');
    await page.keyboard.press('A');
    await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    await page.type('.repo-input', 'vidipt9090/flakeguard-demo');
    repoVal = await page.$eval('.repo-input', (el) => el.value);
    assert('Repository text input accepts typing', repoVal === 'vidipt9090/flakeguard-demo');

    // Test Options Checkboxes & Inputs
    const checkboxes = await page.$$('.checkbox-option input[type=checkbox]');
    assert('Options checkboxes present', checkboxes.length === 2);

    // Toggle Isolate in Docker
    const dockerInitial = await checkboxes[0].evaluate((el) => el.checked);
    await checkboxes[0].click();
    const dockerAfter = await checkboxes[0].evaluate((el) => el.checked);
    assert('Toggle Isolate in Docker checkbox', dockerAfter === !dockerInitial, `Now: ${dockerAfter}`);
    await checkboxes[0].click(); // toggle back

    // Toggle Run on Actions
    const actionsInitial = await checkboxes[1].evaluate((el) => el.checked);
    await checkboxes[1].click();
    const actionsAfter = await checkboxes[1].evaluate((el) => el.checked);
    assert('Toggle Run on GitHub Actions checkbox', actionsAfter === !actionsInitial, `Now: ${actionsAfter}`);
    await checkboxes[1].click(); // toggle back

    // Number input: Perturbation runs (N)
    const numInput = await page.$('.checkbox-option input[type=number]');
    await numInput.click();
    await page.focus('.checkbox-option input[type=number]');
    await page.keyboard.press('ArrowUp');
    const nVal = await numInput.evaluate((el) => el.value);
    assert('Perturbation runs number input adjustable', parseInt(nVal) >= 1, `Value: ${nVal}`);

    // 3. Triage Findings & Filters
    console.log('\n3. Testing Triage Findings Feed & Action Buttons...');
    const findingCards = await page.$$('.finding-card');
    assert('Finding cards rendered', findingCards.length >= 1, `Found ${findingCards.length} cards`);

    // Test Filter buttons: All / Flaky / Real bugs
    const filterBtns = await page.$$('.filter-btn');
    assert('Filter buttons present', filterBtns.length === 3);

    // Click "Flaky"
    await filterBtns[1].click();
    await delay(200);
    const flakyCards = await page.$$('.finding-card');
    const flakyCardBadges = await page.$$eval('.finding-badge', (els) => els.map((e) => e.textContent));
    assert('Filter "Flaky" active', flakyCardBadges.every((b) => b.includes('Flaky')), `Count: ${flakyCards.length}`);

    // Click "Real bugs"
    await filterBtns[2].click();
    await delay(200);
    const realCards = await page.$$('.finding-card');
    const realCardBadges = await page.$$eval('.finding-badge', (els) => els.map((e) => e.textContent));
    assert('Filter "Real bugs" active', realCardBadges.every((b) => b.includes('Real bug')), `Count: ${realCards.length}`);

    // Click "All"
    await filterBtns[0].click();
    await delay(200);

    // Test External Hyperlink "Open in GitHub Actions ↗"
    const ghActionsLink = await page.$eval('.btn-link-actions', (el) => el.href);
    assert('GitHub Actions external hyperlink valid', ghActionsLink.includes('github.com') && ghActionsLink.includes('/actions'), `Href: ${ghActionsLink}`);

    // 4. Test Finding Drawer ("See the proof")
    console.log('\n4. Testing Finding Drawer ("See the proof")...');
    const proofBtns = await page.$$('.btn-see-proof');
    assert('"See the proof" button exists', proofBtns.length > 0);
    await proofBtns[0].click();
    await page.waitForSelector('.drawer-content', { visible: true, timeout: 5000 });

    const drawerTitle = await page.$eval('.drawer-test-title', (el) => el.textContent.trim());
    assert('Finding Drawer opened with test title', drawerTitle.length > 0, `Test: ${drawerTitle}`);

    // Check sections inside Finding Drawer
    const sectionTitles = await page.$$eval('.drawer-section-title', (els) => els.map((e) => e.textContent.trim()));
    assert('Finding Drawer has "HOW WE KNOW"', sectionTitles.includes('HOW WE KNOW'));
    assert('Finding Drawer has "WHERE IT LIVES"', sectionTitles.includes('WHERE IT LIVES'));
    assert('Finding Drawer has "CODE THE MODEL READ"', sectionTitles.some((s) => s.includes('CODE THE MODEL READ')));

    // Test Q&A in Finding Drawer ("Ask about this failure")
    const askInput = await page.$('.ask-input');
    assert('Finding Drawer Q&A input exists', askInput !== null);
    await page.focus('.ask-input');
    await page.keyboard.down('Control');
    await page.keyboard.press('A');
    await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    await page.type('.ask-input', 'Why does this test fail?');
    const askSubmitBtn = await page.$('.ask-btn');
    await askSubmitBtn.click();
    await page.waitForSelector('.answer-box', { visible: true, timeout: 10000 });

    const ragAnswer = await page.$eval('.answer-box', (el) => el.textContent.trim());
    assert('Finding Drawer Q&A returns answer with citations', ragAnswer.length > 0, `Answer snippet: "${ragAnswer.substring(0, 60)}..."`);

    // Close Finding Drawer
    const closeBtn = await page.$('.drawer-close');
    await closeBtn.click();
    await page.waitForSelector('.drawer-content', { hidden: true, timeout: 3000 });
    assert('Finding Drawer closed via Close button', true);

    // 5. Test Fix PR Drawer ("Propose fix PR")
    console.log('\n5. Testing Fix PR Drawer ("Propose fix PR")...');
    const fixBtns = await page.$$('.btn-propose-fix');
    assert('"Propose fix PR" button exists', fixBtns.length > 0);
    await fixBtns[0].click();
    await page.waitForSelector('.fix-pr-drawer', { visible: true, timeout: 5000 });

    const fixTitle = await page.$eval('.fix-pr-drawer .drawer-title', (el) => el.textContent.trim());
    assert('Fix PR Drawer opened', fixTitle.length > 0, `Title: ${fixTitle}`);

    // Check sections inside Fix PR Drawer
    const fixSectionLabels = await page.$$eval('.fix-pr-drawer .section-label', (els) => els.map((e) => e.textContent.trim()));
    assert('Fix PR Drawer has "WHAT THE FIX DOES"', fixSectionLabels.includes('WHAT THE FIX DOES'));
    assert('Fix PR Drawer has "THE CHANGE"', fixSectionLabels.includes('THE CHANGE'));
    assert('Fix PR Drawer has "CHECKED BEFORE OPENING"', fixSectionLabels.includes('CHECKED BEFORE OPENING'));
    assert('Fix PR Drawer has "WHAT HAPPENS NEXT"', fixSectionLabels.includes('WHAT HAPPENS NEXT'));

    // Check Diff contains cleanup fixture
    const diffText = await page.$eval('.code-diff-card', (el) => el.textContent);
    assert('Code diff contains autouse cleanup fixture', diffText.includes('@pytest.fixture(autouse=True)'));

    // Check "Not now" button closes drawer
    const notNowBtn = await page.$('.btn-action-secondary');
    await notNowBtn.click();
    await page.waitForSelector('.fix-pr-drawer', { hidden: true, timeout: 3000 });
    assert('"Not now" button closes Fix PR Drawer', true);

    // Reopen and test "Open pull request on your fork" button
    await fixBtns[0].click();
    await page.waitForSelector('.fix-pr-drawer', { visible: true, timeout: 5000 });
    const openPRBtn = await page.$('.btn-action-primary');
    await openPRBtn.click();
    await delay(500);

    const prSuccessText = await page.$eval('.pr-opened-banner', (el) => el.textContent);
    assert('Pull request opened on fork successfully', prSuccessText.includes('Fix prepared') || prSuccessText.includes('Pull request opened'), `Output: ${prSuccessText}`);

    // Close drawer
    await page.click('.fix-drawer-header .drawer-close-btn');
    await page.waitForSelector('.fix-pr-drawer', { hidden: true, timeout: 3000 });

    // 6. Test Quarantine Action Button
    console.log('\n6. Testing Quarantine Action Button...');
    const quarantineBtns = await page.$$('.btn-quarantine');
    if (quarantineBtns.length > 0) {
      await quarantineBtns[0].click();
      await delay(500);
      const noticeBanner = await page.$eval('.action-notice-banner', (el) => el.textContent);
      assert('Quarantine action executed and notification shown', noticeBanner.includes('quarantine') || noticeBanner.includes('Test'), `Notice: ${noticeBanner}`);
      // Dismiss notice
      await page.click('.notice-dismiss');
    }

    // 7. Test Tab 2 — Repo Map
    console.log('\n7. Testing Tab 2 — Repo Map...');
    const tabBtns = await page.$$('.nav-tab-btn');
    await tabBtns[1].click(); // Repo map tab
    await page.waitForSelector('.repomap-container', { visible: true, timeout: 5000 });

    const repoMapHeading = await page.$eval('.repomap-title', (el) => el.textContent.trim());
    assert('Repo Map view loaded', repoMapHeading === 'Repo map');

    const progressText = await page.$eval('.progress-title', (el) => el.textContent.trim());
    assert('Reading code progress bar present', progressText.includes('Reading the code'));

    // Check tree node items
    const treeNodes = await page.$$('.tree-node-row');
    assert('AST Knowledge tree nodes present', treeNodes.length > 0, `Node count: ${treeNodes.length}`);

    // Select a node (e.g. orders.py or pending_orders)
    await treeNodes[1].click();
    await delay(300);

    const inspectorTitle = await page.$eval('.detail-title', (el) => el.textContent.trim());
    assert('Node Inspector displays selected node', inspectorTitle.length > 0, `Inspecting: ${inspectorTitle}`);

    // Test Q&A in Repo Map Inspector
    const repomapAskInput = await page.$('.ask-input');
    await repomapAskInput.click();
    await page.type('.ask-input', 'Which tests write to this variable?');
    const repomapAskBtn = await page.$('.btn-ask-submit');
    await repomapAskBtn.click();
    await page.waitForSelector('.answer-text', { visible: true, timeout: 10000 });

    const repomapAnswer = await page.$eval('.answer-text', (el) => el.textContent.trim());
    assert('Repo Map Node Q&A returns citation response', repomapAnswer.length > 0, `Answer snippet: "${repomapAnswer.substring(0, 50)}..."`);

    // 8. Test Tab 3 — Pipeline
    console.log('\n8. Testing Tab 3 — Pipeline...');
    const navTabsPipeline = await page.$$('.nav-tab-btn');
    await navTabsPipeline[2].click(); // Pipeline tab
    await page.waitForSelector('.pipeline-container', { visible: true, timeout: 5000 });

    const pipelineHeading = await page.$eval('.pipeline-title', (el) => el.textContent.trim());
    assert('Pipeline view loaded', pipelineHeading === 'Pipeline');

    await page.waitForSelector('.run-card', { visible: true, timeout: 5000 });
    const recentRunItems = await page.$$('.run-card');
    assert('Recent runs list rendered', recentRunItems.length > 0, `Runs count: ${recentRunItems.length}`);

    // Verify "WHERE IT RAN" column / grid
    const whereItRanTitle = await page.$eval('.section-title', (el) => el.textContent.trim());
    assert('"WHERE IT RAN" column present', whereItRanTitle.length > 0);

    // Verify Sandbox badge
    const sandboxBadge = await page.$eval('.sandbox-pill', (el) => el.textContent.trim());
    assert('Sandbox badge displayed honestly', sandboxBadge.length > 0, `Sandbox: "${sandboxBadge}"`);

    // Verify Human steps checklist
    const humanChecklist = await page.$$('.checklist-row');
    assert('Human steps checklist present', humanChecklist.length === 3);

    // 9. Test Tab 4 — Results
    console.log('\n9. Testing Tab 4 — Results...');
    const navTabsResults = await page.$$('.nav-tab-btn');
    await navTabsResults[3].click(); // Results tab
    await page.waitForSelector('.results-container', { visible: true, timeout: 5000 });

    const resultsTitle = await page.$eval('.results-title', (el) => el.textContent.trim());
    assert('Results view loaded', resultsTitle === 'Results');

    await page.waitForSelector('.table-card', { visible: true, timeout: 5000 });

    // Test Segmented Control: Planted / Injected / Natural
    const segmentBtns = await page.$$('.tab-btn');
    assert('Segmented control has 3 benchmarks', segmentBtns.length === 3);

    // Click "Planted"
    await segmentBtns[0].click();
    await delay(200);
    let provChips = await page.$$('.source-chip');
    assert('Planted benchmark table has provenance chips', provChips.length > 0);

    // Click provenance chip to test Provenance Modal
    await provChips[0].click();
    await page.waitForSelector('.provenance-modal', { visible: true, timeout: 3000 });
    const modalTitle = await page.$eval('.modal-title', (el) => el.textContent.trim());
    assert('Provenance modal opened on click', modalTitle === 'Record Provenance');
    await page.click('.modal-close');
    await page.waitForSelector('.provenance-modal', { hidden: true, timeout: 3000 });
    assert('Provenance modal closed via ✕ button', true);

    // Click "Injected"
    await segmentBtns[1].click();
    await delay(200);
    provChips = await page.$$('.source-chip');
    assert('Injected benchmark table has provenance chips', provChips.length > 0);

    // Click "Natural"
    await segmentBtns[2].click();
    await delay(200);
    provChips = await page.$$('.source-chip');
    assert('Natural benchmark table has provenance chips', provChips.length > 0);

    // 10. Test Flow B — No Tests View
    console.log('\n10. Testing Flow B — No Tests View...');
    await tabBtns[0].click(); // Return to Triage
    await page.waitForSelector('.start-hero-card', { visible: true, timeout: 5000 });

    await page.focus('.repo-input');
    await page.keyboard.down('Control');
    await page.keyboard.press('A');
    await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    await page.type('.repo-input', 'tests/data/notest/app.py');
    await delay(300);

    const notestTitle = await page.$eval('.notest-title', (el) => el.textContent.trim());
    assert('No Tests View loaded', notestTitle === 'This repository has no tests');

    // 4-step strip in No Tests view
    const notestSteps = await page.$$('.notest-step');
    assert('No Tests 4-step strip present', notestSteps.length === 4);

    // Risky spots table
    const tableRows = await page.$$('.risky-table tbody tr');
    assert('Risky spots table populated', tableRows.length >= 4, `Rows: ${tableRows.length}`);

    // Kept / Dropped badges
    const statusBadges = await page.$$eval('.badge-result', (els) => els.map((e) => e.textContent.trim()));
    assert('Kept / Dropped badges present', statusBadges.some((s) => s.includes('Kept')) && statusBadges.some((s) => s.includes('Dropped')));

    // One of the kept tests preview
    const keptCode = await page.$eval('.code-example-card', (el) => el.textContent);
    assert('One of kept tests preview contains code', keptCode.includes('def test_'));

    // Pull request button in No Tests view
    const notestPRBtn = await page.$('.btn-action-primary');
    assert('"Open pull request with kept tests" button present', notestPRBtn !== null);
    await notestPRBtn.click();
    await delay(300);
    const prSuccessBadge = await page.$eval('.pr-opened-pill', (el) => el.textContent);
    assert('No Tests PR opened on fork confirmation', prSuccessBadge.includes('Pull request opened on your fork'));

    // Summary
    console.log('\n=============================================================');
    const totalTests = results.length;
    const passedTests = results.filter((r) => r.pass).length;
    const failedTests = results.filter((r) => !r.pass).length;
    console.log(`TOTAL TESTS: ${totalTests} | PASSED: ${passedTests} | FAILED: ${failedTests} | PAGE ERRORS: ${errors.length}`);
    console.log('=============================================================\n');

    await browser.close();
    process.exit(failedTests > 0 || errors.length > 0 ? 1 : 0);
  } catch (err) {
    console.error('[UNHANDLED RUNNER ERROR]', err);
    await browser.close();
    process.exit(1);
  }
}

runTests();
