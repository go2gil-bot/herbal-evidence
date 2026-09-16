/* Phase 1: the landing page only. Auth and the request form arrive in phase 4. */
(function () {
  "use strict";

  var config = window.APP_CONFIG || {};

  if (config.APP_ENV === "dev") {
    var banner = document.getElementById("env-banner");
    if (banner) banner.hidden = false;
  }

  var line = document.getElementById("build-line");
  if (line) {
    line.textContent = "שלב 1 — שלד. הרשמה, שליחת בקשה וקריאת תשובה טרם פעילות.";
  }

  // Registration and login are not wired yet; say so instead of failing silently.
  document.querySelectorAll("[data-nav]").forEach(function (el) {
    el.addEventListener("click", function (event) {
      event.preventDefault();
      window.alert("ההרשמה והכניסה ייפתחו בשלב מאוחר יותר של הפיתוח.");
    });
  });
})();
