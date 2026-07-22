var SUMICORE_FUSIONSOLAR_PROPERTIES = Object.freeze({
  baseUrl: "FUSIONSOLAR_BASE_URL",
  stationDn: "FUSIONSOLAR_STATION_DN",
  cookie: "FUSIONSOLAR_COOKIE",
  csrfToken: "FUSIONSOLAR_CSRF_TOKEN",
  queueFolderId: "SUMICORE_QUEUE_FOLDER_ID"
});

function loadFusionSolarConfig_() {
  var properties = PropertiesService.getScriptProperties();
  var config = {};
  Object.keys(SUMICORE_FUSIONSOLAR_PROPERTIES).forEach(function (field) {
    var name = SUMICORE_FUSIONSOLAR_PROPERTIES[field];
    var value = String(properties.getProperty(name) || "").trim();
    if (!value) {
      throw new Error("Missing Script Property: " + name);
    }
    config[field] = value;
  });
  if (!/^https:\/\/[A-Za-z0-9.-]+(?::[0-9]+)?$/.test(config.baseUrl)) {
    throw new Error("FUSIONSOLAR_BASE_URL must be an HTTPS origin without a path");
  }
  return config;
}
