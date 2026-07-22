function FusionSolarSession_(config) {
  this.config = config;
}

var SUMICORE_FUSIONSOLAR_MAX_RESPONSE_BYTES = 10 * 1024 * 1024;

FusionSolarSession_.prototype.getJson = function (path, query) {
  var pairs = Object.keys(query).map(function (key) {
    return encodeURIComponent(key) + "=" + encodeURIComponent(String(query[key]));
  });
  return this.fetchJson_(path + "?" + pairs.join("&"), "get");
};

FusionSolarSession_.prototype.postJson = function (path, payload) {
  return this.fetchJson_(path, "post", JSON.stringify(payload));
};

FusionSolarSession_.prototype.fetchJson_ = function (path, method, payload) {
  var options = {
    method: method,
    muteHttpExceptions: true,
    followRedirects: false,
    headers: {
      Accept: "application/json, text/plain, */*",
      Cookie: this.config.cookie,
      Referer: this.config.baseUrl + "/pvmswebsite/assets/build/index.html",
      "X-Requested-With": "XMLHttpRequest",
      "X-Timezone-Offset": "540",
      "X-Non-Renewal-Session": "true",
      roarand: this.config.csrfToken
    }
  };
  if (method === "post") {
    options.contentType = "application/json;charset=UTF-8";
    options.payload = payload;
    options.headers.Origin = this.config.baseUrl;
  }
  var response = UrlFetchApp.fetch(this.config.baseUrl + path, options);
  var status = response.getResponseCode();
  var contentType = String(response.getHeaders()["Content-Type"] || "").toLowerCase();
  if (status === 401 || status === 403 || (status >= 300 && status < 400)) {
    throw new Error("FusionSolar session is not authenticated (HTTP " + status + ")");
  }
  if (status < 200 || status >= 300) {
    throw new Error("FusionSolar request failed (HTTP " + status + ")");
  }
  if (contentType.indexOf("text/html") !== -1) {
    throw new Error("FusionSolar returned HTML instead of JSON");
  }
  var responseBytes = response.getBlob().getBytes().length;
  if (responseBytes > SUMICORE_FUSIONSOLAR_MAX_RESPONSE_BYTES) {
    throw new Error("FusionSolar response exceeds the 10 MiB safety limit");
  }
  try {
    return JSON.parse(response.getContentText("UTF-8"));
  } catch (error) {
    throw new Error("FusionSolar response is not valid JSON");
  }
};
