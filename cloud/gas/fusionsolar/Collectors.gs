function tokyoDate_(date) {
  return Utilities.formatDate(date, "Asia/Tokyo", "yyyy-MM-dd");
}

function previousTokyoDate_() {
  return tokyoDate_(new Date(Date.now() - 24 * 60 * 60 * 1000));
}

function collectEnergyBalance_(session, config, targetDate) {
  var targetMidnight = new Date(targetDate + "T00:00:00+09:00");
  var query = {
    stationDn: config.stationDn,
    timeDim: "2",
    queryTime: targetMidnight.getTime(),
    timeZone: "9",
    timeZoneStr: "Asia/Tokyo",
    dateStr: targetDate + " 00:00:00",
    _: Date.now()
  };
  var payload = session.getJson(
    "/rest/pvms/web/station/v1/overview/energy-balance",
    query
  );
  return queueRawData_(config, "fusionsolar_energy_balance", targetDate, {
    method: "GET",
    endpoint: "/rest/pvms/web/station/v1/overview/energy-balance",
    timeDim: "2"
  }, payload);
}

function collectStationKpi_(session, config, targetDate) {
  var targetMidnight = new Date(targetDate + "T00:00:00+09:00");
  var body = {
    currencyUnit: "¥",
    counterIDs: [
      "productPower", "inverterPower", "onGridPower", "buyPower", "powerProfit"
    ],
    moList: [{moType: 20801, moString: config.stationDn}],
    orderBy: "fmtCollectTimeStr",
    page: 1,
    pageSize: 100,
    sort: "asc",
    statDim: "2",
    statTime: targetMidnight.getTime(),
    statType: "1",
    station: "1",
    timeZone: 9,
    timeZoneStr: "Asia/Tokyo"
  };
  var payload = session.postJson(
    "/rest/pvms/web/report/v1/station/station-kpi-list",
    body
  );
  return queueRawData_(config, "fusionsolar", targetDate, {
    method: "POST",
    endpoint: "/rest/pvms/web/report/v1/station/station-kpi-list",
    statDim: "2"
  }, payload);
}

function collectFusionSolarPreviousDay() {
  var config = loadFusionSolarConfig_();
  var session = new FusionSolarSession_(config);
  var targetDate = previousTokyoDate_();
  var results = [];
  [collectEnergyBalance_, collectStationKpi_].forEach(function (collector) {
    try {
      results.push(collector(session, config, targetDate));
    } catch (error) {
      results.push({status: "failed", error_type: error.name || "Error"});
    }
  });
  if (results.some(function (result) { return result.status === "failed"; })) {
    throw new Error("One or more FusionSolar collections failed");
  }
  return results;
}
