/* Landing page only. Signed-in pages use core.js. */
(function () {
  "use strict";

  var config = window.APP_CONFIG || {};

  if (config.APP_ENV === "dev") {
    var banner = document.getElementById("env-banner");
    if (banner) banner.hidden = false;
  }

  // Someone already signed in should not be asked to sign in again.
  try {
    if (window.localStorage.getItem("he.session")) {
      document.querySelectorAll('a[href="auth.html"]').forEach(function (link) {
        link.href = "dashboard.html";
        if (link.textContent.trim() === "כניסה") link.textContent = "הבקשות שלי";
        if (link.textContent.trim() === "הרשמה") link.textContent = "בקשה חדשה";
      });
    }
  } catch (err) {
    /* storage blocked; the links stay as they are */
  }
})();
