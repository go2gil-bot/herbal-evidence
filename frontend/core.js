/* Shared session and API helpers.
 *
 * Auth goes straight to Supabase Auth from the browser with the publishable key.
 * Everything else goes to our own backend, which verifies the token and applies
 * authorization server-side. The browser never holds a secret key.
 */
(function (global) {
  "use strict";

  var config = global.APP_CONFIG || {};
  var SESSION_KEY = "he.session";

  function authUrl(path) {
    return String(config.SUPABASE_URL || "").replace(/\/$/, "") + "/auth/v1" + path;
  }

  function apiUrl(path) {
    return String(config.API_BASE_URL || "").replace(/\/$/, "") + path;
  }

  /* --- session ---------------------------------------------------------- */

  function readSession() {
    try {
      var raw = global.localStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      // Private windows and blocked site data both land here.
      return null;
    }
  }

  function writeSession(session) {
    try {
      if (session) {
        global.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      } else {
        global.localStorage.removeItem(SESSION_KEY);
      }
    } catch (err) {
      /* nothing to do; the page still works for this tab */
    }
  }

  function isExpired(session) {
    if (!session || !session.expires_at) return true;
    return Date.now() / 1000 > session.expires_at - 30;
  }

  /* --- supabase auth ---------------------------------------------------- */

  function authFetch(path, body) {
    return fetch(authUrl(path), {
      method: "POST",
      headers: {
        apikey: config.SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var error = new Error(data.msg || data.error_description || data.message || "שגיאה");
          error.status = response.status;
          error.code = data.error_code || data.code;
          throw error;
        }
        return data;
      });
    });
  }

  var auth = {
    signUp: function (email, password) {
      return authFetch("/signup", {
        email: email,
        password: password,
        options: { email_redirect_to: global.location.origin + "/auth.html?verified=1" }
      });
    },

    signIn: function (email, password) {
      return authFetch("/token?grant_type=password", { email: email, password: password })
        .then(function (data) {
          writeSession(data);
          return data;
        });
    },

    resetPassword: function (email) {
      return authFetch("/recover", {
        email: email,
        options: { email_redirect_to: global.location.origin + "/auth.html?reset=1" }
      });
    },

    refresh: function () {
      var session = readSession();
      if (!session || !session.refresh_token) return Promise.reject(new Error("no session"));
      return authFetch("/token?grant_type=refresh_token", { refresh_token: session.refresh_token })
        .then(function (data) {
          writeSession(data);
          return data;
        });
    },

    signOut: function () {
      writeSession(null);
      global.location.href = "index.html";
    },

    session: readSession,

    requireSession: function () {
      var session = readSession();
      if (!session || !session.access_token) {
        global.location.href = "auth.html?next=" + encodeURIComponent(global.location.pathname);
        return null;
      }
      return session;
    }
  };

  /* --- our API ---------------------------------------------------------- */

  function call(method, path, body, retried) {
    var session = readSession();
    if (!session) return Promise.reject(new Error("not signed in"));

    var start = isExpired(session) && !retried ? auth.refresh() : Promise.resolve(session);

    return start.then(function (current) {
      return fetch(apiUrl(path), {
        method: method,
        headers: {
          Authorization: "Bearer " + current.access_token,
          "Content-Type": "application/json"
        },
        body: body ? JSON.stringify(body) : undefined
      });
    }).then(function (response) {
      if (response.status === 401 && !retried) {
        return auth.refresh().then(function () { return call(method, path, body, true); });
      }
      return response.json().catch(function () { return null; }).then(function (data) {
        if (!response.ok) {
          var detail = (data && data.detail) || {};
          var error = new Error(detail.message || "לא ניתן היה להשלים את הפעולה");
          error.status = response.status;
          error.code = detail.code;
          throw error;
        }
        return data;
      });
    });
  }

  var api = {
    identify: function (query) {
      return call("GET", "/api/v1/plants/identify?q=" + encodeURIComponent(query));
    },
    createRequest: function (payload) { return call("POST", "/api/v1/requests", payload); },
    listRequests: function () { return call("GET", "/api/v1/requests"); },
    getRequest: function (id) { return call("GET", "/api/v1/requests/" + id); },
    getResponse: function (id) { return call("GET", "/api/v1/requests/" + id + "/response"); },
    answerClarification: function (requestId, clarificationId, answer) {
      return call(
        "POST",
        "/api/v1/requests/" + requestId + "/clarifications/" + clarificationId,
        { answer: answer }
      );
    }
  };

  /* --- presentation ----------------------------------------------------- */

  // Status is never carried by colour alone: every one of these is a word.
  var STATUS_TEXT = {
    received: "התקבלה",
    clarification_needed: "נדרשת הבהרה",
    under_review: "בבדיקה",
    response_available: "תשובה זמינה",
    closed: "נסגרה"
  };

  var IDENTIFICATION_TEXT = {
    pending: "הצמח נשלח לבדיקה אנושית",
    resolved: "הצמח זוהה",
    ambiguous: "נדרשת הבהרה לגבי הצמח",
    multi_ingredient: "מוצר רב-רכיבי",
    out_of_scope: "מחוץ להיקף"
  };

  function formatDate(value) {
    if (!value) return "";
    var date = new Date(value);
    return date.toLocaleDateString("he-IL", { year: "numeric", month: "2-digit", day: "2-digit" });
  }

  /* Latin text inside Hebrew needs isolation or the punctuation jumps around. */
  function ltr(text) {
    var span = document.createElement("span");
    span.className = "ltr";
    span.dir = "ltr";
    span.textContent = text;
    return span;
  }

  function showError(container, message) {
    if (!container) return;
    container.textContent = message;
    container.hidden = false;
  }

  function clearError(container) {
    if (!container) return;
    container.textContent = "";
    container.hidden = true;
  }

  function markDevEnvironment() {
    if (config.APP_ENV === "dev") {
      var banner = document.getElementById("env-banner");
      if (banner) banner.hidden = false;
    }
  }

  global.HE = {
    config: config,
    auth: auth,
    api: api,
    STATUS_TEXT: STATUS_TEXT,
    IDENTIFICATION_TEXT: IDENTIFICATION_TEXT,
    formatDate: formatDate,
    ltr: ltr,
    showError: showError,
    clearError: clearError,
    markDevEnvironment: markDevEnvironment
  };
})(window);
