var SUMICORE_FUSIONSOLAR_AUTH_ALERT_EMAIL_PROPERTY = "SUMICORE_AUTH_ALERT_EMAIL";
var SUMICORE_FUSIONSOLAR_AUTH_LAST_NOTIFIED_PROPERTY = "SUMICORE_FUSIONSOLAR_AUTH_LAST_NOTIFIED_AT";
var SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_COOLDOWN_MS = 6 * 60 * 60 * 1000;

function FusionSolarAuthenticationError_(reason, httpStatus) {
  this.name = "FusionSolarAuthenticationError";
  this.reason = reason;
  this.httpStatus = httpStatus;
  this.message = "FusionSolar authentication expired (" + reason + ")";
}
FusionSolarAuthenticationError_.prototype = Object.create(Error.prototype);
FusionSolarAuthenticationError_.prototype.constructor = FusionSolarAuthenticationError_;

function fusionSolarAuthenticationFailureReason_(status, contentType) {
  if (status === 401 || status === 403) {
    return "http_" + status;
  }
  if (status >= 300 && status < 400) {
    return "redirect";
  }
  if (status >= 200 && status < 300 &&
      String(contentType || "").toLowerCase().indexOf("text/html") !== -1) {
    return "html_response";
  }
  return "";
}

function reportFusionSolarAuthenticationExpired_(reason, now) {
  var detectedAt = now || new Date();
  var properties = PropertiesService.getScriptProperties();
  var detectedIso = detectedAt.toISOString();
  properties.setProperties({
    SUMICORE_FUSIONSOLAR_AUTH_STATUS: "expired",
    SUMICORE_FUSIONSOLAR_AUTH_LAST_DETECTED_AT: detectedIso,
    SUMICORE_FUSIONSOLAR_AUTH_LAST_REASON: reason
  }, false);

  var recipient = String(
    properties.getProperty(SUMICORE_FUSIONSOLAR_AUTH_ALERT_EMAIL_PROPERTY) || ""
  ).trim();
  if (!recipient) {
    properties.setProperty("SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_STATE", "recipient_not_configured");
    return {status: "recorded", notification: "recipient_not_configured"};
  }

  var lastNotifiedMs = Date.parse(String(
    properties.getProperty(SUMICORE_FUSIONSOLAR_AUTH_LAST_NOTIFIED_PROPERTY) || ""
  ));
  if (!isNaN(lastNotifiedMs) &&
      detectedAt.getTime() - lastNotifiedMs < SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_COOLDOWN_MS) {
    properties.setProperty("SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_STATE", "cooldown");
    return {status: "recorded", notification: "cooldown"};
  }

  try {
    MailApp.sendEmail({
      to: recipient,
      subject: "[SumiCore] FusionSolarの再認証が必要です",
      body: [
        "FusionSolarの認証期限切れを検知しました。",
        "検知時刻: " + detectedIso,
        "検知種別: " + reason,
        "",
        "CookieとCSRFを安全な手順で更新してください。",
        "認証情報そのものはこの通知に含まれていません。"
      ].join("\n"),
      name: "SumiCore"
    });
    properties.setProperties({
      SUMICORE_FUSIONSOLAR_AUTH_LAST_NOTIFIED_AT: detectedIso,
      SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_STATE: "sent"
    }, false);
    return {status: "recorded", notification: "sent"};
  } catch (error) {
    properties.setProperty("SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_STATE", "failed");
    return {status: "recorded", notification: "failed"};
  }
}

function reportFusionSolarAuthenticationHealthy_(now) {
  var properties = PropertiesService.getScriptProperties();
  var previous = String(
    properties.getProperty("SUMICORE_FUSIONSOLAR_AUTH_STATUS") || ""
  );
  var values = {
    SUMICORE_FUSIONSOLAR_AUTH_STATUS: "healthy",
    SUMICORE_FUSIONSOLAR_AUTH_LAST_SUCCESS_AT: (now || new Date()).toISOString()
  };
  if (previous === "expired") {
    values.SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_STATE = "recovered";
  }
  properties.setProperties(values, false);
  return {status: "healthy", recovered: previous === "expired"};
}

function throwFusionSolarAuthenticationExpired_(reason, status) {
  reportFusionSolarAuthenticationExpired_(reason);
  throw new FusionSolarAuthenticationError_(reason, status);
}
