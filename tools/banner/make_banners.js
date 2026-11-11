// Renders the Qt Shell banners from banner.html (1280x640) and banner_wide.html (1280x400).
// Run from the repo root:  node tools/banner/make_banners.js   (needs Playwright with Chromium)
// Then: qt_shell/banner.png (startup banner), docs/logo/qt_shell_banner_1280x640.png,
// docs/logo/qt_shell_banner.png (README), site/img/og.jpg (web link preview, convert the 1280x640 PNG to JPEG).
const {chromium} = require('playwright');
const path = require('path');
(async () => {
  const dir = __dirname;
  const b = await chromium.launch();
  for (const [f, h, outs] of [
    ['banner.html', 640, ['qt_shell/banner.png', 'docs/logo/qt_shell_banner_1280x640.png']],
    ['banner_wide.html', 400, ['docs/logo/qt_shell_banner.png']]]) {
    const p = await b.newPage({viewport: {width: 1280, height: h}, deviceScaleFactor: 1});
    await p.goto('file://' + path.join(dir, f));
    await p.waitForTimeout(400);
    for (const o of outs) await p.screenshot({path: o});
    await p.close();
  }
  await b.close();
})();
