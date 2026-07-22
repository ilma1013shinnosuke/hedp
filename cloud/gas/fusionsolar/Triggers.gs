function installFusionSolarDailyTrigger() {
  var functionName = "collectFusionSolarPreviousDay";
  var previousTriggers = ScriptApp.getProjectTriggers().filter(function (trigger) {
    return trigger.getHandlerFunction() === functionName;
  });
  var newTrigger = ScriptApp.newTrigger(functionName)
    .timeBased()
    .atHour(4)
    .nearMinute(30)
    .everyDays(1)
    .inTimezone("Asia/Tokyo")
    .create();
  previousTriggers.forEach(function (trigger) {
    if (trigger.getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  return {status: "installed", trigger_id: newTrigger.getUniqueId()};
}
