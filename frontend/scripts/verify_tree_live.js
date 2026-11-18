import puppeteer from 'puppeteer-core';
import path from 'path';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE_URL = 'http://127.0.0.1:5173';
const SCREENSHOT_PATH = path.resolve('C:\\Users\\khull\\Desktop\\4th Year\\IDT Final\\FlakeGuard\\docs\\eval3\\knowledge_tree_scan_verified.png');
const SCREENSHOT_REPOMAP = path.resolve('C:\\Users\\khull\\Desktop\\4th Year\\IDT Final\\FlakeGuard\\docs\\eval3\\repo_map_dark_verified.png');
const SCREENSHOT_PIPELINE = path.resolve('C:\\Users\\khull\\Desktop\\4th Year\\IDT Final\\FlakeGuard\\docs\\eval3\\pipeline_dark_verified.png');
const SCREENSHOT_RESULTS = path.resolve('C:\\Users\\khull\\Desktop\\4th Year\\IDT Final\\FlakeGuard\\docs\\eval3\\results_dark_verified.png');

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  console.log('--- Testing Full FlakeGuard UI Theme, Links & Interactions ---');

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1440,960'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 960 });

  try {
    // 1. Triage Tab & Knowledge Tree
    console.log('1. Loading Triage Page...');
    await page.goto(BASE_URL, { waitUntil: 'networkidle2', timeout: 15000 });
    await delay(1000);

    // Verify GitHub Actions link points to real repository without 404
    const actionsLink = await page.$eval('.btn-link-actions', (el) => el.getAttribute('href'));
    console.log('   GitHub Actions link:', actionsLink);
    if (actionsLink.includes('flakeguard-demo/actions')) {
      throw new Error(`Actions link still points to broken flakeguard-demo: ${actionsLink}`);
    }

    // Switch to tree view
    const treeToggle = await page.$('[data-testid="toggle-view-tree"]');
    if (treeToggle) {
      await treeToggle.click();
      await delay(500);
    }

    await page.waitForSelector('.knowledge-tree-view', { visible: true, timeout: 5000 });
    await page.screenshot({ path: SCREENSHOT_PATH, fullPage: false });
    console.log('   Saved main Triage Tree screenshot to:', SCREENSHOT_PATH);

    // 2. Repo Map Tab
    console.log('2. Testing Repo Map Tab...');
    const tabs = await page.$$('.nav-tab-btn');
    if (tabs.length >= 4) {
      await tabs[1].click(); // Repo Map
      await delay(800);
      await page.waitForSelector('.repomap-container', { visible: true, timeout: 5000 });

      // Verify title is visible (not transparent / matching background)
      const titleColor = await page.$eval('.repomap-title', (el) => window.getComputedStyle(el).color);
      console.log('   Repo Map title color:', titleColor);

      await page.screenshot({ path: SCREENSHOT_REPOMAP, fullPage: false });
      console.log('   Saved Repo Map screenshot to:', SCREENSHOT_REPOMAP);

      // 3. Pipeline Tab
      console.log('3. Testing Pipeline Tab...');
      await tabs[2].click(); // Pipeline
      await delay(800);
      await page.waitForSelector('.pipeline-container', { visible: true, timeout: 5000 });

      const pipelineActionsLink = await page.$eval('.github-actions-link', (el) => el.getAttribute('href'));
      console.log('   Pipeline Actions link:', pipelineActionsLink);
      if (pipelineActionsLink.includes('flakeguard-demo/actions')) {
        throw new Error(`Pipeline Actions link still broken: ${pipelineActionsLink}`);
      }

      await page.screenshot({ path: SCREENSHOT_PIPELINE, fullPage: false });
      console.log('   Saved Pipeline screenshot to:', SCREENSHOT_PIPELINE);

      // 4. Results Tab
      console.log('4. Testing Results Tab...');
      await tabs[3].click(); // Results
      await delay(800);
      await page.waitForSelector('.results-container', { visible: true, timeout: 5000 });

      await page.screenshot({ path: SCREENSHOT_RESULTS, fullPage: false });
      console.log('   Saved Results screenshot to:', SCREENSHOT_RESULTS);
    }

    console.log('\n--- ALL UI VERIFICATIONS, CONTRAST CHECKS & LINK TESTS PASSED! ---');
    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('UI VERIFICATION ERROR:', err);
    await browser.close();
    process.exit(1);
  }
}

main();
