import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const playwrightPath = process.env.PLAYWRIGHT_CORE_PATH;
const browserPath = process.env.BROWSER_PATH;
if (!playwrightPath || !browserPath) {
  throw new Error("PLAYWRIGHT_CORE_PATH and BROWSER_PATH are required");
}
const { chromium } = require(playwrightPath);

const root = process.cwd();
const categories = [
  ["memory_retrieval", "记忆检索（从记忆中提取过去的经历、事实或其他相关信息）"],
  ["content_planning", "内容规划（规划接下来要表达的内容、信息顺序及具体展开方式）"],
  ["lexical_retrieval", "词汇检索（检索或选择表达当前意思所需的某个单词或词组）"],
  ["sentence_organization", "句式组织（选择或重新组织表达当前意思的句式，包括比较不同表达方案、安排词序及确定分句关系）"],
  ["phonological_encoding", "语音编码（准备或确认即将说出的词语的发音形式及语音实现方式）"],
  ["emphatic_pause", "强调性停顿（通过停顿突出后续内容的重要性、对比关系或转折）"],
  ["physiological_pause", "生理性停顿（因换气、咳嗽等生理需要暂时中断表达）"],
  ["other", "其他（如转录错误等，请与现场主试说明情况）"],
].map(([value, label]) => ({ value, label }));

const patches = [];
const session = {
  session_id: "test-session",
  title: "多原因点选测试",
  status: "in_progress",
  instruction: null,
  utterances: [{
    id: "utterance-1",
    seq: 1,
    speaker: "participant",
    text: "I play more often than not, like very often.",
    raw_text: "I play more often than not,<PAUSE:0.63s> like very often.",
    annotation_targets: [{
      id: "target-1",
      utterance_id: "utterance-1",
      target_index: 0,
      label: "pause",
      required: true,
      display_hint: "停顿 0.63s",
      pause_duration_ms: 630,
      annotation: null,
    }],
  }],
};

function send(res, status, contentType, body) {
  res.writeHead(status, { "Content-Type": contentType });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  if (req.method === "GET" && url.pathname === "/a/test") {
    return send(res, 200, "text/html; charset=utf-8", fs.readFileSync(path.join(root, "static/participant.html")));
  }
  if (req.method === "GET" && url.pathname === "/css/style.css") {
    return send(res, 200, "text/css; charset=utf-8", fs.readFileSync(path.join(root, "static/css/style.css")));
  }
  if (req.method === "GET" && url.pathname === "/api/admin/settings") {
    return send(res, 200, "application/json", JSON.stringify({ reason_categories: categories }));
  }
  if (req.method === "GET" && url.pathname === "/api/a/test") {
    return send(res, 200, "application/json", JSON.stringify(session));
  }
  if (req.method === "PATCH" && url.pathname.includes("/annotations/")) {
    let body = "";
    req.on("data", chunk => { body += chunk; });
    req.on("end", () => {
      patches.push(JSON.parse(body));
      send(res, 200, "application/json", JSON.stringify({ ok: true, is_complete: false }));
    });
    return;
  }
  send(res, 404, "text/plain", "Not found");
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const browser = await chromium.launch({ headless: true, executablePath: browserPath });

try {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    await page.goto(`http://127.0.0.1:${port}/a/test`, { waitUntil: "networkidle" });

    const choices = page.locator(".reason-choice");
    assert(await choices.count() === 8, `${viewport.width}px: expected eight visible reasons`);
    const titles = page.locator(".reason-choice-title");
    const explanations = page.locator(".reason-choice-explanation");
    assert(await titles.count() === 8, `${viewport.width}px: expected eight bold reason titles`);
    assert(await explanations.count() === 8, `${viewport.width}px: expected eight normal-weight explanations`);
    const titleWeights = await titles.evaluateAll(nodes => nodes.map(node => getComputedStyle(node).fontWeight));
    const explanationWeights = await explanations.evaluateAll(nodes => nodes.map(node => getComputedStyle(node).fontWeight));
    assert(titleWeights.every(weight => weight === "700" || weight === "bold"), `${viewport.width}px: reason titles are not bold`);
    assert(explanationWeights.every(weight => weight === "400" || weight === "normal"), `${viewport.width}px: reason explanations are not normal weight`);
    const minimumHeight = Math.min(...await choices.evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height)));
    assert(minimumHeight >= 44, `${viewport.width}px: reason touch target is below 44px`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert(!overflow, `${viewport.width}px: page has horizontal overflow`);

    if (viewport.width === 1280) {
      const inputs = page.locator(".reason-choice-input");
      await inputs.nth(0).check();
      await inputs.nth(1).check();
      assert(await page.locator(".reason-choice-input:checked").count() === 2, "two reasons were not selected");
      assert(await page.locator(".reason-choice-input:disabled:not(:checked)").count() === 6, "remaining reasons were not disabled at the limit");
      assert((await page.locator(".reason-choice-count").textContent()).includes("2/2"), "selection count did not update");

      await inputs.nth(0).uncheck();
      await inputs.nth(6).check();
      assert(await page.locator(".conditional-annotation-fields").isHidden(), "physiological pause did not hide extra fields");
      await page.waitForTimeout(900);
      assert(patches.some(body => Array.isArray(body.categories) && body.categories.length === 2), "two selected reasons were not autosaved");
    }
    await page.close();
  }
  console.log("reason multi-select UI passed desktop and 390px checks");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
