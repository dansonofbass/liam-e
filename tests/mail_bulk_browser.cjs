// Driven by test_mail_bulk_trash_sync_pg.py with BULK_TEST_WEB_ORIGIN set to the built app.
const assert = require("node:assert/strict");
const http = require("node:http");
const { chromium } = require("playwright");

async function run(webOrigin, apiOrigin, selected) {
  for (const origin of [webOrigin, apiOrigin]) assert.equal(new URL(origin).hostname, "127.0.0.1");
  const browser = await chromium.launch({ executablePath: process.env.BULK_TEST_CHROMIUM });
  // Serve the built UI and its real per-test API under one origin, as in the deployed app.
  const server = http.createServer((request, response) => {
    const origin = request.url.startsWith("/api/") ? apiOrigin : webOrigin;
    const upstream = http.request(origin, { method: request.method, path: request.url, headers: request.headers }, incoming => {
      response.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(response);
    });
    upstream.on("error", error => response.destroy(error));
    response.on("close", () => upstream.destroy());
    request.pipe(upstream);
  });
  try {
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    const origin = "http://127.0.0.1:" + server.address().port;
    const context = await browser.newContext({ locale: "de-DE", serviceWorkers: "block" });
    await context.route(url => url.origin !== origin, route => route.abort());
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    await page.goto(origin + "/mail");
    await page.getByRole("button", { name: "Auswählen", exact: true }).click();
    for (const subject of selected) {
      await page.getByRole("button", { name: "Auswählen: " + subject, exact: true }).click();
    }
    await page.getByText(selected.length + " ausgewählt", { exact: true }).waitFor();
    const action = (path, label) => Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === path && r.request().method() === "POST"),
      page.getByRole("button", { name: label, exact: true }).click(),
    ]).then(([r]) => r);
    const bulk = await action("/api/v1/mail/messages/actions", "In den Papierkorb");
    assert.equal(bulk.status(), 200);
    const results = (await bulk.json()).results;
    const toast = page.locator(".le-inbox-toast");
    await toast.getByRole("button", { name: "Rückgängig" }).waitFor();
    const text = await toast.innerText();
    const tone = await toast.locator(".le-notice").getAttribute("role");

    // A second tab can reload the real list without dismissing the first tab's undo notice.
    const observer = await context.newPage();
    function expectVisible(tab, subjects) {
      return tab.waitForFunction(expected => {
        const visible = Array.from(document.querySelectorAll(".le-mailrow-subject"), e => e.textContent).sort();
        return JSON.stringify(visible) === JSON.stringify(expected);
      }, subjects);
    }
    async function inspect(stage) {
      const response = await context.request.post(apiOrigin + "/_test/phase/" + stage);
      assert.equal(response.status(), 200);
      const { INBOX } = await response.json();
      if (stage === "immediate") await expectVisible(page, INBOX);
      const listRead = observer.waitForResponse(r => new URL(r.url()).pathname === "/api/v1/mail/messages");
      if (observer.url() === "about:blank") await observer.goto(origin + "/mail");
      else await observer.reload();
      const listed = (await (await listRead).json()).items.map(row => row.subject).sort();
      assert.deepEqual(listed, INBOX);
      await expectVisible(observer, INBOX);
    }
    for (const stage of ["immediate", "delayed", "replay", "fresh"]) await inspect(stage);
    const undo = await action("/api/v1/mail/actions/undo", "Rückgängig");
    await inspect("undone");
    await inspect("restored");
    return { request: bulk.request().postDataJSON(), results, toast: text, tone,
      undo_ids: undo.request().postDataJSON().action_ids, undo_status: undo.status(),
      undo: undo.ok() ? await undo.json() : {} };
  } finally {
    await browser.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}

const [web, api, selected] = process.argv.slice(2);
run(web, api, JSON.parse(selected)).then(result => console.log(JSON.stringify(result)))
  .catch(error => { console.error(error); process.exitCode = 1; });
