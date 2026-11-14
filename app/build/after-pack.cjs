/**
 * after-pack.cjs — gives "Knowledge Bank.exe" its own icon and details.
 *
 * WHAT:  Runs automatically during the installer build, right after
 *        electron-builder has assembled the app folder and before it wraps it
 *        into the installer. It edits the app's .exe so that:
 *          - the taskbar, desktop and Start-menu shortcuts show the Knowledge
 *            Bank icon (not Electron's default atom icon)
 *          - Properties → Details and Task Manager show "Knowledge Bank",
 *            its version and copyright instead of "Electron"
 *
 * WHY:   electron-builder normally does this with a Windows-only tool
 *        (rcedit) that needs Wine when building on Linux. The pure-JavaScript
 *        library "resedit" does the same job on any OS, so the installer can
 *        be built in Claude's Linux workspace. That's why package.json sets
 *        "signAndEditExecutable": false and points "afterPack" here.
 *
 * WHEN:  Only during `npm run dist:win` (tools/build-windows.sh). Never at
 *        runtime.
 *
 * CONNECTED TO: app/package.json ("build.afterPack", "build.win"),
 *        app/build/icon.ico, tools/build-windows.sh.
 */
const fs = require("node:fs");
const path = require("node:path");

/**
 * electron-builder calls this with `context` describing the packed app.
 * context.appOutDir = folder containing "<productName>.exe".
 */
exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "win32") return; // Windows builds only

  // resedit is ESM-only, so it's loaded with a dynamic import.
  const ResEdit = await import("resedit");
  const { productFilename, info } = context.packager.appInfo;
  const exePath = path.join(context.appOutDir, `${productFilename}.exe`);
  const iconPath = path.join(context.packager.info.buildResourcesDir, "icon.ico");

  // Load the .exe and its resource section (where icons and version info live).
  const exe = ResEdit.NtExecutable.from(fs.readFileSync(exePath), { ignoreCert: true });
  const res = ResEdit.NtExecutableResource.from(exe);

  // --- Icon: replace Electron's main icon group (id 1) with ours.
  const iconFile = ResEdit.Data.IconFile.from(fs.readFileSync(iconPath));
  ResEdit.Resource.IconGroupEntry.replaceIconsForResource(
    res.entries,
    1,
    1033, // language: English (United States)
    iconFile.icons.map((item) => item.data)
  );

  // --- Version details shown in Properties → Details and Task Manager.
  const version = info.version || "0.0.0";
  const [major, minor, patch] = version.split(".").map((n) => parseInt(n, 10) || 0);
  const vi = ResEdit.Resource.VersionInfo.fromEntries(res.entries)[0];
  vi.setFileVersion(major, minor, patch, 0, 1033);
  vi.setProductVersion(major, minor, patch, 0, 1033);
  vi.setStringValues(
    { lang: 1033, codepage: 1200 },
    {
      FileDescription: info.productName,
      ProductName: info.productName,
      CompanyName: "Vishal Singh",
      LegalCopyright: info.copyright || "",
      OriginalFilename: `${productFilename}.exe`,
      InternalName: productFilename,
      FileVersion: version,
      ProductVersion: version,
    }
  );
  vi.outputToResourceEntries(res.entries);

  // Write the edited resources back into the .exe.
  res.outputResource(exe);
  fs.writeFileSync(exePath, Buffer.from(exe.generate()));
  console.log(`  • after-pack: icon and version info set on ${path.basename(exePath)}`);
};
