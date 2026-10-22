<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-xs">Billing Integrity</div>
    <p class="text-grey-7">
      Membership subscriptions where MemberMatters and Stripe disagree. The
      check compares them every night and only reports what it finds: fix each
      issue in Stripe or on the member, and the next run resolves it.
    </p>

    <template v-if="status">
      <q-banner
        v-for="banner in banners"
        :key="banner"
        :class="bannerClass(banner)"
        class="rounded-borders q-mb-md"
      >
        {{ bannerText(banner, status.lastRun) }}
      </q-banner>

      <q-card flat bordered class="q-mb-md">
        <q-card-section class="row q-col-gutter-md">
          <div class="col-12 col-sm-4">
            <div class="text-caption text-grey-7">Last run</div>
            <template v-if="status.lastRun">
              <div>
                {{ formatDate(status.lastRun.startedAt) }}
                <q-badge
                  :color="runStatusColor(status.lastRun.status)"
                  class="q-ml-xs"
                >
                  {{ runStatusLabel(status.lastRun.status) }}
                </q-badge>
              </div>
              <div class="text-caption text-grey-7">
                {{ status.lastRun.stripeRequests }} Stripe requests,
                {{ status.lastRun.membersChecked }} members checked
              </div>
            </template>
            <div v-else>Never</div>
          </div>

          <div class="col-12 col-sm-4">
            <div class="text-caption text-grey-7">Last complete run</div>
            <div>
              {{
                status.lastCompleteRun?.finishedAt
                  ? formatWhen(status.lastCompleteRun.finishedAt)
                  : 'Never'
              }}
            </div>
          </div>

          <div class="col-12 col-sm-4">
            <div class="text-caption text-grey-7">Next run</div>
            <div>
              {{
                status.nextRun ? formatDate(status.nextRun) : 'Not scheduled'
              }}
            </div>
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none text-caption text-grey-7">
          {{ scheduleText(status.schedule) }}
        </q-card-section>
      </q-card>

      <div class="row q-gutter-sm q-mb-md">
        <q-chip
          v-for="severity in severities"
          :key="severity"
          :color="severityColor(severity)"
          text-color="white"
        >
          {{ severityLabel(severity) }}: {{ status.counts[severity] }}
        </q-chip>
        <q-chip outline>
          Acknowledged: {{ status.counts.acknowledged }}
        </q-chip>
      </div>
    </template>

    <q-table
      :rows="issues"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :no-data-label="noIssuesLabel"
      :pagination="{ rowsPerPage: 25 }"
      :grid="view === 'cards'"
      flat
      bordered
    >
      <template v-slot:top>
        <div class="row q-gutter-sm items-center full-width">
          <q-select
            v-model="filters.status"
            :options="statusOptions"
            label="Show"
            emit-value
            map-options
            outlined
            dense
            style="min-width: 200px"
            @update:model-value="fetchIssues"
          />
          <q-select
            v-model="filters.severity"
            :options="severityOptions"
            label="Severity"
            emit-value
            map-options
            outlined
            dense
            style="min-width: 140px"
            @update:model-value="fetchIssues"
          />
          <q-select
            v-if="sourceOptions.length > 3"
            v-model="filters.source"
            :options="sourceOptions"
            label="Source"
            emit-value
            map-options
            outlined
            dense
            style="min-width: 160px"
            @update:model-value="fetchIssues"
          />
          <q-space />
          <q-btn-toggle
            v-model="view"
            :options="viewOptions"
            no-caps
            unelevated
            toggle-color="primary"
            color="grey-3"
            text-color="dark"
          />
          <q-btn
            color="primary"
            icon="mdi-play"
            label="Run now"
            :loading="runQueued"
            :disable="!status?.enabled"
            @click="runNow"
          />
        </div>
      </template>

      <template v-slot:body="props">
        <q-tr
          :props="props"
          class="cursor-pointer"
          @click="props.expand = !props.expand"
        >
          <q-td key="severity" :props="props">
            <q-icon
              :name="props.expand ? 'mdi-chevron-down' : 'mdi-chevron-right'"
              class="q-mr-xs"
            />
            <q-badge :color="severityColor(props.row.severity)">
              {{ severityLabel(props.row.severity) }}
            </q-badge>
          </q-td>
          <q-td key="member" :props="props">
            <router-link
              v-if="props.row.memberId"
              :to="{
                name: 'manageMember',
                params: { memberId: props.row.memberId },
              }"
              @click.stop
            >
              {{ props.row.memberName }}
            </router-link>
            <span v-else class="text-grey-7">Stripe account</span>
          </q-td>
          <q-td key="message" :props="props">{{ props.row.message }}</q-td>
          <q-td key="mm" :props="props">{{ props.row.mm || '—' }}</q-td>
          <q-td key="stripe" :props="props">{{ props.row.stripe || '—' }}</q-td>
          <q-td key="firstSeen" :props="props">
            {{ formatDate(props.row.firstSeen) }}
            <div class="text-caption text-grey-7">
              {{ seenIn(props.row.occurrences) }}
            </div>
          </q-td>
          <q-td key="actions" :props="props" class="text-no-wrap">
            <q-btn
              v-if="props.row.stripeUrl"
              flat
              round
              dense
              color="primary"
              icon="mdi-open-in-new"
              aria-label="Open in Stripe"
              type="a"
              :href="props.row.stripeUrl"
              target="_blank"
              rel="noopener"
              @click.stop
            >
              <q-tooltip>Open in Stripe</q-tooltip>
            </q-btn>
            <template v-if="!props.row.resolvedAt">
              <q-btn
                v-if="props.row.acknowledged"
                flat
                round
                dense
                icon="mdi-undo"
                aria-label="Withdraw the acknowledgement"
                @click.stop="withdraw(props.row)"
              >
                <q-tooltip>Withdraw the acknowledgement</q-tooltip>
              </q-btn>
              <q-btn
                v-else
                flat
                round
                dense
                color="positive"
                icon="mdi-check"
                aria-label="Acknowledge"
                @click.stop="openAcknowledge(props.row)"
              >
                <q-tooltip>Acknowledge</q-tooltip>
              </q-btn>
            </template>
          </q-td>
        </q-tr>
        <q-tr v-show="props.expand" :props="props">
          <q-td colspan="100%" style="white-space: normal">
            <billing-issue-details :issue="props.row" class="q-pa-sm" />
          </q-td>
        </q-tr>
      </template>

      <template v-slot:item="props">
        <div class="q-pa-xs col-12 col-md-6">
          <q-card flat bordered class="full-height column">
            <q-card-section class="q-pb-sm">
              <div class="row items-center q-gutter-x-sm">
                <q-badge :color="severityColor(props.row.severity)">
                  {{ severityLabel(props.row.severity) }}
                </q-badge>
                <router-link
                  v-if="props.row.memberId"
                  :to="{
                    name: 'manageMember',
                    params: { memberId: props.row.memberId },
                  }"
                >
                  {{ props.row.memberName }}
                </router-link>
                <span v-else class="text-grey-7">Stripe account</span>
              </div>
              <div class="text-subtitle1 q-mt-xs">{{ props.row.message }}</div>
            </q-card-section>

            <q-card-section class="q-py-none col-grow">
              <div>
                <span class="text-grey-7">MemberMatters says:</span>
                {{ props.row.mm || '—' }}
              </div>
              <div class="q-mb-sm">
                <span class="text-grey-7">Stripe says:</span>
                {{ props.row.stripe || '—' }}
              </div>
              <billing-issue-details :issue="props.row" />
              <div class="text-caption text-grey-7 q-mt-xs">
                First seen {{ formatDate(props.row.firstSeen) }},
                {{ seenIn(props.row.occurrences) }}
              </div>
            </q-card-section>

            <q-card-actions align="right">
              <q-btn
                v-if="props.row.stripeUrl"
                flat
                dense
                color="primary"
                icon="mdi-open-in-new"
                label="Open in Stripe"
                type="a"
                :href="props.row.stripeUrl"
                target="_blank"
                rel="noopener"
              />
              <template v-if="!props.row.resolvedAt">
                <q-btn
                  v-if="props.row.acknowledged"
                  flat
                  dense
                  icon="mdi-undo"
                  label="Withdraw"
                  @click="withdraw(props.row)"
                />
                <q-btn
                  v-else
                  flat
                  dense
                  color="positive"
                  icon="mdi-check"
                  label="Acknowledge"
                  @click="openAcknowledge(props.row)"
                />
              </template>
            </q-card-actions>
          </q-card>
        </div>
      </template>
    </q-table>

    <q-dialog v-model="acknowledgeDialog">
      <q-card style="min-width: 350px; max-width: 500px">
        <q-card-section>
          <div class="text-h6">Acknowledge issue</div>
        </q-card-section>

        <q-card-section v-if="selectedIssue" class="q-pt-none">
          <div class="q-mb-sm">
            <strong>{{ selectedIssue.memberName || 'Stripe account' }}</strong>
            — {{ selectedIssue.message }}
          </div>
          <p class="text-caption text-grey-7 q-mb-md">
            An acknowledged issue stays here until the check no longer finds it,
            but doesn't cause any more emails. Say why, for the other admins.
          </p>
          <q-input
            v-model="note"
            type="textarea"
            rows="3"
            outlined
            label="Note (optional)"
            maxlength="1000"
            counter
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup :disable="submitting" />
          <q-btn
            color="positive"
            label="Acknowledge"
            :loading="submitting"
            @click="confirmAcknowledge"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import formatMixin from '@mixins/formatMixin';
import BillingIssueDetails from '@components/AdminTools/BillingIssueDetails.vue';
import type {
  IntegrityIssue,
  IntegrityStatus,
  RunStatus,
  Severity,
} from 'types/billingIntegrity';
import {
  SEVERITIES,
  apiMessage,
  bannerText,
  compareIssues,
  runFinished,
  runStatusLabel,
  scheduleText,
  seenIn,
  severityColor,
  severityLabel,
  statusBanners,
  StatusBanner,
} from '../../utils/billingIntegrity';

// How often, and how many times, to look for the end of a queued run.
const POLL_INTERVAL_MS = 5000;
const MAX_POLLS = 24;

const RUN_STATUS_COLORS: Record<RunStatus, string> = {
  running: 'info',
  complete: 'positive',
  incomplete: 'warning',
  failed: 'negative',
};

const FETCH_ERROR = "Couldn't load the billing check.";
const UPDATE_ERROR = "Couldn't update the issue.";

const NO_ISSUES: Record<string, string> = {
  open: 'No open issues.',
  acknowledged: 'No acknowledged issues.',
  resolved: 'No issues resolved in the last 90 days.',
};

export default defineComponent({
  name: 'BillingIntegrity',
  components: { BillingIssueDetails },
  mixins: [formatMixin],
  data() {
    return {
      // Cards suit a phone; the table suits a wide screen. Either can be
      // picked with the toggle.
      view: this.$q.screen.lt.md ? 'cards' : 'table',
      status: null as IntegrityStatus | null,
      issues: [] as IntegrityIssue[],
      loading: false,
      filters: { status: 'open', severity: '', source: '' },
      acknowledgeDialog: false,
      selectedIssue: null as IntegrityIssue | null,
      note: '',
      submitting: false,
      runQueued: false,
      pollTimer: null as ReturnType<typeof setTimeout> | null,
    };
  },
  computed: {
    severities(): Severity[] {
      return SEVERITIES;
    },
    banners(): StatusBanner[] {
      return this.status ? statusBanners(this.status) : [];
    },
    statusOptions() {
      return [
        { label: 'Open', value: 'open' },
        { label: 'Acknowledged', value: 'acknowledged' },
        { label: 'Resolved in the last 90 days', value: 'resolved' },
      ];
    },
    severityOptions() {
      return [
        { label: 'All', value: '' },
        ...SEVERITIES.map((severity) => ({
          label: severityLabel(severity),
          value: severity,
        })),
      ];
    },
    // Offered only once a second local source exists, beside the Stripe
    // account checks.
    sourceOptions() {
      const sources = this.status?.sources ?? [];
      return [
        { label: 'All', value: '' },
        ...sources.map((source) => ({
          label: source.label,
          value: source.value,
        })),
      ];
    },
    viewOptions() {
      return [
        { label: 'Table', value: 'table', icon: 'mdi-table' },
        { label: 'Cards', value: 'cards', icon: 'mdi-view-agenda-outline' },
      ];
    },
    noIssuesLabel(): string {
      return NO_ISSUES[this.filters.status] ?? NO_ISSUES.open;
    },
    columns() {
      return [
        {
          name: 'severity',
          label: 'Severity',
          field: 'severity',
          align: 'left' as const,
        },
        {
          name: 'member',
          label: 'Member',
          field: 'memberName',
          align: 'left' as const,
          sortable: true,
        },
        {
          name: 'message',
          label: 'Issue',
          field: 'message',
          align: 'left' as const,
        },
        {
          name: 'mm',
          label: 'MemberMatters says',
          field: 'mm',
          align: 'left' as const,
        },
        {
          name: 'stripe',
          label: 'Stripe says',
          field: 'stripe',
          align: 'left' as const,
        },
        {
          name: 'firstSeen',
          label: 'First seen',
          field: 'firstSeen',
          align: 'left' as const,
          sortable: true,
        },
        {
          name: 'actions',
          label: '',
          field: 'id',
          align: 'right' as const,
        },
      ];
    },
  },
  mounted() {
    this.refresh();
  },
  beforeUnmount() {
    this.stopPolling();
  },
  methods: {
    bannerText,
    runStatusLabel,
    scheduleText,
    seenIn,
    severityColor,
    severityLabel,
    refresh() {
      this.fetchStatus();
      this.fetchIssues();
    },
    fetchStatus() {
      this.$axios
        .get('/api/admin/billing/integrity/')
        .then((response) => {
          this.status = response.data;
        })
        .catch(() => {
          this.$q.notify({ type: 'negative', message: FETCH_ERROR });
        });
    },
    fetchIssues() {
      this.loading = true;
      const params = Object.fromEntries(
        Object.entries(this.filters).filter(([, value]) => value)
      );
      this.$axios
        .get('/api/admin/billing/integrity/issues/', { params })
        .then((response) => {
          this.issues = [...response.data].sort(compareIssues);
        })
        .catch(() => {
          this.$q.notify({ type: 'negative', message: FETCH_ERROR });
        })
        .finally(() => {
          this.loading = false;
        });
    },
    openAcknowledge(issue: IntegrityIssue) {
      this.selectedIssue = issue;
      this.note = '';
      this.acknowledgeDialog = true;
    },
    confirmAcknowledge() {
      if (!this.selectedIssue) return;
      this.submitting = true;
      this.$axios
        .post(
          `/api/admin/billing/integrity/issues/${this.selectedIssue.id}/acknowledge/`,
          { note: this.note }
        )
        .then(() => {
          this.$q.notify({ type: 'positive', message: 'Issue acknowledged.' });
          this.acknowledgeDialog = false;
          this.refresh();
        })
        .catch(() => {
          this.$q.notify({ type: 'negative', message: UPDATE_ERROR });
        })
        .finally(() => {
          this.submitting = false;
        });
    },
    withdraw(issue: IntegrityIssue) {
      this.$axios
        .delete(`/api/admin/billing/integrity/issues/${issue.id}/acknowledge/`)
        .then(() => {
          this.$q.notify({
            type: 'positive',
            message: 'Acknowledgement withdrawn.',
          });
          this.refresh();
        })
        .catch(() => {
          this.$q.notify({ type: 'negative', message: UPDATE_ERROR });
        });
    },
    runNow() {
      const previousRunId = this.status?.lastRun?.id ?? null;
      this.runQueued = true;
      this.$axios
        .post('/api/admin/billing/integrity/run/')
        .then(() => {
          this.$q.notify({
            type: 'info',
            message:
              'The check has started. This page updates when it finishes.',
          });
          this.pollForRun(previousRunId, 0);
        })
        .catch((error) => {
          this.$q.notify({
            type: 'negative',
            message: apiMessage(
              error.response?.data?.message,
              "Couldn't start the check."
            ),
          });
          this.runQueued = false;
        });
    },
    pollForRun(previousRunId: number | null, polls: number) {
      this.pollTimer = setTimeout(() => {
        this.$axios
          .get('/api/admin/billing/integrity/')
          .then((response) => {
            this.status = response.data;
            if (this.status && runFinished(previousRunId, this.status)) {
              this.runQueued = false;
              this.fetchIssues();
            } else if (polls + 1 < MAX_POLLS) {
              this.pollForRun(previousRunId, polls + 1);
            } else {
              this.runQueued = false;
            }
          })
          .catch(() => {
            this.runQueued = false;
          });
      }, POLL_INTERVAL_MS);
    },
    stopPolling() {
      if (this.pollTimer) clearTimeout(this.pollTimer);
      this.pollTimer = null;
    },
    runStatusColor(status: RunStatus): string {
      return RUN_STATUS_COLORS[status] ?? 'grey';
    },
    bannerClass(banner: StatusBanner): string {
      if (banner === 'disabled') return 'bg-grey-3 text-dark';
      if (banner === 'lastRunIncomplete') return 'bg-warning text-dark';
      return 'bg-negative text-white';
    },
  },
});
</script>
