/**
 * patch-nsis-no-wine.cjs — lets electron-builder make the NSIS installer on Linux without running it under Wine.
 *
 * WHAT:  electron-builder creates the uninstaller by running the half-built installer once. On Linux it does that with
 *        Wine. It also ships a pure-JavaScript reader (nsisUtil.UninstallerReader) that pulls the same uninstaller out of
 *        the installer file, but only uses it on macOS. This script makes the Linux path try that reader first and fall
 *        back to Wine only if the reader fails. The installer that comes out is the same.
 * WHY:   v0.23.0 build (18 Nov 2026): after a workspace restart Wine 9.0 crashed at start-up on the new kernel
 *        ("free(): invalid pointer", even with a fresh prefix), so the installer step failed. Wine is still used for the
 *        engine smoke test when it works, but no longer needed to build.
 * WHEN:  tools/build-windows.sh runs it after `npm install`, before `npm run dist:win`. Safe to run any number of times
 *        (it does nothing if the patch is already in place).
 * CONNECTED TO: app/node_modules/app-builder-lib/out/targets/nsis/NsisTarget.js (patched in place; node_modules is not
 *        in git, so the build script re-applies it after every install).
 */
const fs = require("node:fs");
const path = require("node:path");

const file = path.join(__dirname, "..", "app", "node_modules", "app-builder-lib", "out", "targets", "nsis", "NsisTarget.js");
const MARK = "/* KB: uninstaller without Wine */";
const OLD = `            await (0, wine_1.execWine)(installerPath, null, [], { env: { __COMPAT_LAYER: "RunAsInvoker" } });`;
const NEW = `            ${MARK}
            try {
                await nsisUtil_1.UninstallerReader.exec(installerPath, uninstallerPath);
            }
            catch (error) {
                builder_util_1.log.warn(\`uninstaller reader failed, using Wine: \${error.message}\`);
                await (0, wine_1.execWine)(installerPath, null, [], { env: { __COMPAT_LAYER: "RunAsInvoker" } });
            }`;

const src = fs.readFileSync(file, "utf8");
if (src.includes(MARK)) {
  console.log("patch-nsis-no-wine: already applied");
} else if (!src.includes(OLD)) {
  console.error("patch-nsis-no-wine: electron-builder changed; the line to patch was not found (build will need Wine)");
  process.exit(1);
} else {
  fs.writeFileSync(file, src.replace(OLD, NEW));
  console.log("patch-nsis-no-wine: applied");
}
