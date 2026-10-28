// Puts the theme the viewer chose (or the system's) on the page before it is
// drawn, so that a dark page does not flash light first. A file of its own:
// the app's Content-Security-Policy allows no inline script.
(() => {
  let preference = "system";
  try {
    preference = localStorage.getItem("sardonyx.theme") || "system";
  } catch {
    // storage may be blocked; the system's theme then
  }
  // Dracula is a dark theme: it is drawn as dark, in its own colours
  const dark =
    preference === "dark" ||
    preference === "dracula" ||
    (preference === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.classList.toggle("dracula", preference === "dracula");
})();
