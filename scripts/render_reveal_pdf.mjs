#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import puppeteer from "puppeteer-core";

function usageAndExit(code = 1, msg) {
  if (msg) {
    process.stderr.write(`${msg}\n\n`);
  }
  process.stderr.write(
    [
      "Usage: render_reveal_pdf.mjs --browser <path> --url <url> --out <pdf> [--timeout-ms <ms>]",
      "",
      "Renders a Reveal.js deck to PDF using the deck's ?print-pdf mode.",
    ].join("\n") + "\n",
  );
  process.exit(code);
}

function parseArgs(argv) {
  const args = {
    browser: null,
    url: null,
    out: null,
    timeoutMs: 120000,
  };

  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--browser") {
      args.browser = argv[++i] ?? null;
    } else if (a === "--url") {
      args.url = argv[++i] ?? null;
    } else if (a === "--out") {
      args.out = argv[++i] ?? null;
    } else if (a === "--timeout-ms") {
      args.timeoutMs = Number(argv[++i] ?? "60000");
    } else {
      usageAndExit(1, `Unknown arg: ${a}`);
    }
  }

  if (!args.browser || !args.url || !args.out) {
    usageAndExit(1, "Missing required arguments.");
  }
  if (!Number.isFinite(args.timeoutMs) || args.timeoutMs <= 0) {
    usageAndExit(1, "Invalid --timeout-ms value.");
  }
  return args;
}

async function waitForRevealReady(page, timeoutMs) {
  await page.waitForFunction(
    () => {
      const reveal = globalThis.Reveal;
      return typeof reveal?.isReady === "function" && reveal.isReady();
    },
    { timeout: timeoutMs },
  );
}

async function waitForImages(page, timeoutMs) {
  await page.waitForFunction(
    () => Array.from(document.images || []).every((img) => img.complete && img.naturalWidth > 0),
    { timeout: timeoutMs },
  );
}

async function hydrateLazyMedia(page) {
  await page.evaluate(() => {
    for (const img of document.querySelectorAll("img[data-src], img[data-srcset]")) {
      if (!img.getAttribute("src") && img.dataset.src) {
        img.src = img.dataset.src;
      }
      if (!img.getAttribute("srcset") && img.dataset.srcset) {
        img.srcset = img.dataset.srcset;
      }
      img.loading = "eager";
    }

    for (const source of document.querySelectorAll("source[data-srcset]")) {
      if (!source.getAttribute("srcset") && source.dataset.srcset) {
        source.srcset = source.dataset.srcset;
      }
    }
  });
}

async function main() {
  const { browser, url, out, timeoutMs } = parseArgs(process.argv);

  await fs.mkdir(path.dirname(out), { recursive: true });

  const browserInstance = await puppeteer.launch({
    executablePath: browser,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--font-render-hinting=none",
    ],
    headless: "new",
    defaultViewport: { width: 1600, height: 900 },
  });

  try {
    const page = await browserInstance.newPage();
    page.setDefaultTimeout(timeoutMs);
    await page.goto(url, { waitUntil: "networkidle2" });
    await waitForRevealReady(page, timeoutMs);
    await hydrateLazyMedia(page);
    await waitForImages(page, timeoutMs).catch((err) => {
      process.stderr.write(`Warning: timed out waiting for images (${timeoutMs}ms): ${err}\n`);
    });

    await fs.writeFile(out, await page.pdf({
      printBackground: true,
      landscape: true,
      displayHeaderFooter: false,
      preferCSSPageSize: true,
    }));
  } finally {
    await browserInstance.close();
  }
}

await main();
