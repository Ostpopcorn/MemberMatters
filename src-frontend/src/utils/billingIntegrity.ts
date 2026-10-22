// The Billing Integrity admin screens are in English only, like the other
// new admin pages; only the menu entry is translated.

import type {
  IntegrityIssue,
  IntegrityRun,
  IntegritySchedule,
  IntegrityStatus,
  RunStatus,
  Severity,
} from '../types/billingIntegrity';

// Most severe first.
export const SEVERITIES: Severity[] = ['critical', 'warning', 'info'];

const SEVERITY_LABELS: Record<Severity, string> = {
  critical: 'Critical',
  warning: 'Warning',
  info: 'Info',
};

const SEVERITY_COLORS: Record<Severity, string> = {
  critical: 'negative',
  warning: 'warning',
  info: 'info',
};

export function severityLabel(severity: Severity): string {
  return SEVERITY_LABELS[severity] ?? severity;
}

export function severityColor(severity: Severity): string {
  return SEVERITY_COLORS[severity] ?? 'grey';
}

const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  running: 'Running',
  complete: 'Complete',
  incomplete: 'Incomplete',
  failed: 'Failed',
};

export function runStatusLabel(status: RunStatus): string {
  return RUN_STATUS_LABELS[status] ?? status;
}

export function seenIn(occurrences: number): string {
  return `seen in ${occurrences} ${occurrences === 1 ? 'run' : 'runs'}`;
}

const WEEKDAYS: Record<string, string> = {
  mon: 'Mondays',
  tue: 'Tuesdays',
  wed: 'Wednesdays',
  thu: 'Thursdays',
  fri: 'Fridays',
  sat: 'Saturdays',
  sun: 'Sundays',
};

export function scheduleText(schedule: IntegritySchedule): string {
  const day = WEEKDAYS[schedule.weeklyDigestDay] ?? schedule.weeklyDigestDay;
  return (
    `The check runs every night at ${schedule.dailyCheckAt}, and a digest ` +
    `goes to the admin email on ${day} at ${schedule.weeklyDigestAt} ` +
    `(${schedule.timeZone}).`
  );
}

// Most severe first, then the oldest, which has waited longest.
export function compareIssues(a: IntegrityIssue, b: IntegrityIssue): number {
  const bySeverity =
    SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity);
  if (bySeverity !== 0) return bySeverity;
  return a.firstSeen.localeCompare(b.firstSeen);
}

export type StatusBanner =
  'disabled' | 'noCelery' | 'stale' | 'lastRunFailed' | 'lastRunIncomplete';

// What the page should warn about, most important first.
export function statusBanners(status: IntegrityStatus): StatusBanner[] {
  if (!status.enabled) return ['disabled'];

  const banners: StatusBanner[] = [];
  if (!status.celeryConfigured) banners.push('noCelery');
  if (status.stale) banners.push('stale');
  if (status.lastRun?.status === 'failed') banners.push('lastRunFailed');
  else if (status.lastRun?.status === 'incomplete') {
    banners.push('lastRunIncomplete');
  }
  return banners;
}

export const CHECK_OFF =
  'The billing check is off. It runs when membership payments are on, a ' +
  'Stripe secret key is set and BILLING_AUDIT_ENABLED is on.';

export const NO_CELERY =
  "Celery isn't configured, so the check doesn't run on its own. Run " +
  'manage.py check_stripe_drift from a daily cron job instead.';

export function bannerText(
  banner: StatusBanner,
  lastRun: IntegrityRun | null
): string {
  switch (banner) {
    case 'disabled':
      return CHECK_OFF;
    case 'noCelery':
      return NO_CELERY;
    case 'stale':
      return (
        'No check has completed in the last 36 hours. Make sure the Celery ' +
        'worker and beat are running.'
      );
    case 'lastRunFailed':
      return `The last check failed: ${lastRun?.error || 'unknown error'}`;
    case 'lastRunIncomplete':
      return `The last check skipped some checks: ${skippedReasons(lastRun)}`;
  }
}

// Why a run skipped checks, each reason once.
export function skippedReasons(run: IntegrityRun | null): string {
  if (!run) return '';
  const reasons = run.skippedChecks
    .map((entry) => entry.reason)
    .filter((reason) => reason);
  return [...new Set(reasons)].join('; ');
}
