var SUMICORE_QUEUE_SCHEMA_VERSION = 1;
var SUMICORE_MAX_ATTEMPTS_PER_SOURCE_DATE = 3;

function queueRawData_(config, source, targetDate, request, payload) {
  var collectedAt = new Date().toISOString();
  var payloadText = JSON.stringify(payload);
  var digest = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    payloadText,
    Utilities.Charset.UTF_8
  );
  var hash = digest.map(function (value) {
    return (value + 256).toString(16).slice(-2);
  }).join("");
  var prefix = source + "_" + targetDate + "_";
  var folder = DriveApp.getFolderById(config.queueFolderId);
  var files = folder.getFiles();
  var attempts = 0;
  while (files.hasNext()) {
    var existing = files.next().getName();
    if (existing.indexOf(prefix) === 0) {
      attempts += 1;
      if (existing === prefix + hash.slice(0, 16) + ".json") {
        return {status: "duplicate", file: existing, hash: hash};
      }
    }
  }
  if (attempts >= SUMICORE_MAX_ATTEMPTS_PER_SOURCE_DATE) {
    throw new Error("Raw queue attempt limit reached for " + source + " " + targetDate);
  }
  var envelope = {
    schema_version: SUMICORE_QUEUE_SCHEMA_VERSION,
    source: source,
    collected_at: collectedAt,
    target_date: targetDate,
    request: request,
    payload_sha256: hash,
    payload: payload
  };
  var name = prefix + hash.slice(0, 16) + ".json";
  folder.createFile(name, JSON.stringify(envelope), MimeType.PLAIN_TEXT);
  return {status: "queued", file: name, hash: hash};
}
