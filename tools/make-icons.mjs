// Regenerates the app icons and header mark from assets/logo.jpg
// (the original Expectation Church logo, dark mark on white).
//
// Uses a headless browser canvas so the logo's exact shapes are kept.
// Needs: `npm i playwright-core` and a Chromium binary, plus a static
// server for the repo root, e.g. `python3 -m http.server 8123`.
//
//   node tools/make-icons.mjs [chromium-path] [base-url]
//
// Outputs: icons/logo-mark.png (white mark, transparent background),
// icons/icon-512.png, icons/icon-192.png, icons/apple-touch-icon.png.

import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import { chromium } from "playwright-core";

const here = path.dirname(url.fileURLToPath(import.meta.url));
const iconsDir = path.join(here, "..", "icons");
const executablePath = process.argv[2] || undefined;
const base = process.argv[3] || "http://localhost:8123";

const browser = await chromium.launch({ executablePath, args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.goto(base + "/index.html");

const result = await page.evaluate(async (base) => {
  const img = new Image();
  img.crossOrigin = "anonymous";
  await new Promise((ok, err) => {
    img.onload = ok;
    img.onerror = err;
    img.src = base + "/assets/logo.jpg";
  });

  // Work at a manageable resolution.
  const W = 2000;
  const H = Math.round((img.height / img.width) * W);
  const src = document.createElement("canvas");
  src.width = W;
  src.height = H;
  const sctx = src.getContext("2d");
  sctx.drawImage(img, 0, 0, W, H);
  const data = sctx.getImageData(0, 0, W, H);
  const px = data.data;

  // Dark pixels become the mark; brightness maps to alpha so the
  // anti-aliased edges from the original survive.
  const alphaAt = (i) => {
    const lum = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    return Math.max(0, Math.min(1, (235 - lum) / 150));
  };

  // Bounding box of the mark.
  let minX = W, minY = H, maxX = 0, maxY = 0;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (alphaAt((y * W + x) * 4) > 0.5) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  const pad = Math.round(Math.max(maxX - minX, maxY - minY) * 0.02);
  minX = Math.max(0, minX - pad);
  minY = Math.max(0, minY - pad);
  maxX = Math.min(W - 1, maxX + pad);
  maxY = Math.min(H - 1, maxY + pad);
  const mw = maxX - minX + 1;
  const mh = maxY - minY + 1;

  // White mark on transparency, cropped.
  const mark = document.createElement("canvas");
  mark.width = mw;
  mark.height = mh;
  const mctx = mark.getContext("2d");
  const mdata = mctx.createImageData(mw, mh);
  for (let y = 0; y < mh; y++) {
    for (let x = 0; x < mw; x++) {
      const a = alphaAt(((y + minY) * W + (x + minX)) * 4);
      const o = (y * mw + x) * 4;
      mdata.data[o] = 255;
      mdata.data[o + 1] = 255;
      mdata.data[o + 2] = 255;
      mdata.data[o + 3] = Math.round(a * 255);
    }
  }
  mctx.putImageData(mdata, 0, 0);

  // App icon: blue gradient rounded tile + centered white mark.
  const tile = (S) => {
    const c = document.createElement("canvas");
    c.width = S;
    c.height = S;
    const ctx = c.getContext("2d");
    const r = S * 0.22;
    ctx.beginPath();
    ctx.moveTo(r, 0);
    ctx.arcTo(S, 0, S, S, r);
    ctx.arcTo(S, S, 0, S, r);
    ctx.arcTo(0, S, 0, 0, r);
    ctx.arcTo(0, 0, S, 0, r);
    ctx.closePath();
    ctx.clip();
    const g = ctx.createLinearGradient(0, 0, 0, S);
    g.addColorStop(0, "#2E6BE6");
    g.addColorStop(1, "#1240A8");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, S, S);
    const dw = S * 0.66;
    const dh = (mh / mw) * dw;
    ctx.drawImage(mark, (S - dw) / 2, (S - dh) / 2, dw, dh);
    return c.toDataURL("image/png");
  };

  return {
    mark: mark.toDataURL("image/png"),
    markAspect: mh / mw,
    icon512: tile(512),
    icon192: tile(192),
    icon180: tile(180),
  };
}, base);

const save = (name, dataUrl) =>
  fs.writeFileSync(path.join(iconsDir, name), Buffer.from(dataUrl.split(",")[1], "base64"));

save("logo-mark.png", result.mark);
save("icon-512.png", result.icon512);
save("icon-192.png", result.icon192);
save("apple-touch-icon.png", result.icon180);
console.log("mark aspect (h/w):", result.markAspect.toFixed(3));
console.log("wrote logo-mark.png, icon-512.png, icon-192.png, apple-touch-icon.png");

await browser.close();
