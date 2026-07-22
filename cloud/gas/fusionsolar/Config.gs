var HEDP_FUSIONSOLAR_PROPERTIES = Object.freeze({
  baseUrl: "FUSIONSOLAR_BASE_URL",
  stationDn: "FUSIONSOLAR_STATION_DN",
  cookie: "FUSIONSOLAR_COOKIE",
  csrfToken: "FUSIONSOLAR_CSRF_TOKEN",
  queueFolderId: "HEDP_QUEUE_FOLDER_ID"
});

function loadFusionSolarConfig_() {
  var properties = PropertiesService.getScriptProperties();
  var config = {};
  Object.keys(HEDP_FUSIONSOLAR_PROPERTIES).forEach(function (field) {
    var name = HEDP_FUSIONSOLAR_PROPERTIES[field];
    var value = String(properties.getProperty(name) || "").trim();
    if (!value) {
      throw new Error("Missing Script Property: " + name);
    }
    config[field] = value;
  });
  if (config.baseUrl.slice(0, 8) !== "https://") {
    throw new Error("FUSIONSOLAR_BASE_URL must use HTTPS");
  }
  return config;
}
