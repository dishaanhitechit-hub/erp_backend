/**
 * ERP backup watchdog — runs inside Google (Apps Script), NOT on the server.
 *
 * If the server is off, has no internet or the disk died, it cannot send a
 * "backup failed" e-mail. This script checks the heartbeat file the backup
 * writes to Google Drive after every successful upload and e-mails the admins
 * when it is too old.
 *
 * Setup (logged in as the backup Google account):
 *   1. script.google.com → New project → paste this file.
 *   2. Edit the CONFIG below.
 *   3. Run checkBackup once and allow the permissions it asks for.
 *   4. Triggers (clock icon) → Add trigger → checkBackup → Time-driven → Every hour.
 */
var CONFIG = {
  HEARTBEAT_PATH: ['ERP-Backups', 'heartbeat.json'],   // must match BACKUP_HEARTBEAT_REMOTE
  MAX_AGE_HOURS: 13,
  ALERT_EMAILS: 'it-admin@example.com,manager@example.com',
  REPEAT_EVERY_HOURS: 6,
};

function checkBackup() {
  var file = findFile_(CONFIG.HEARTBEAT_PATH);
  var problem = null;
  var info = '';
  if (!file) {
    problem = 'heartbeat file not found on Google Drive';
  } else {
    var ageHours = (Date.now() - file.getLastUpdated().getTime()) / 36e5;
    info = file.getBlob().getDataAsString();
    if (ageHours > CONFIG.MAX_AGE_HOURS) {
      problem = 'last backup reached Google Drive ' + ageHours.toFixed(1) + ' hours ago';
    }
  }

  var props = PropertiesService.getScriptProperties();
  if (!problem) {
    props.deleteProperty('lastAlert');
    return;
  }
  var last = Number(props.getProperty('lastAlert') || 0);
  if (Date.now() - last < CONFIG.REPEAT_EVERY_HOURS * 36e5) return;

  MailApp.sendEmail(
    CONFIG.ALERT_EMAILS,
    '[ERP Backup] ALERT — no backup received on Google Drive',
    'Problem: ' + problem + '\n\n' +
    'The server may be switched off, offline, or the backup is failing.\n' +
    'Check the ERP server today.\n\nLast heartbeat:\n' + info
  );
  props.setProperty('lastAlert', String(Date.now()));
}

function findFile_(path) {
  var folder = DriveApp.getRootFolder();
  for (var i = 0; i < path.length - 1; i++) {
    var it = folder.getFoldersByName(path[i]);
    if (!it.hasNext()) return null;
    folder = it.next();
  }
  var files = folder.getFilesByName(path[path.length - 1]);
  return files.hasNext() ? files.next() : null;
}
