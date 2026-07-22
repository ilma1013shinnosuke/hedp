function installFusionSolarDailyTrigger() {
  var functionName = "collectFusionSolarPreviousDay";
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger(functionName)
    .timeBased()
    .atHour(4)
    .nearMinute(30)
    .everyDays(1)
    .inTimezone("Asia/Tokyo")
    .create();
}
