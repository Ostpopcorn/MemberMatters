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
      no-data-label="No open issues."
      :pagination="{ rowsPerPage: 25 }"
      flat
      bordered
    >
      <template v-slot:body-cell-severity="props">
        <q-td :props="props">
          <q-badge :color="severityColor(props.row.severity)">
            {{ severityLabel(props.row.severity) }}
          </q-badge>
        </q-td>
      </template>

      <template v-slot:body-cell-member="props">
        <q-td :props="props">
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
        </q-td>
      </template>

      <template v-slot:body-cell-firstSeen="props">
        <q-td :props="props">
          {{ formatDate(props.row.firstSeen) }}
          <div class="text-caption text-grey-7">
            {{ seenIn(props.row.occurrences) }}
          </div>
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
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
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import formatMixin from '@mixins/formatMixin';
import type {
  IntegrityIssue,
  IntegrityStatus,
  RunStatus,
  Severity,
} from 'types/billingIntegrity';
import {
  SEVERITIES,
  bannerText,
  compareIssues,
  runStatusLabel,
  scheduleText,
  seenIn,
  severityColor,
  severityLabel,
  statusBanners,
  StatusBanner,
} from '../../utils/billingIntegrity';

const RUN_STATUS_COLORS: Record<RunStatus, string> = {
  running: 'info',
  complete: 'positive',
  incomplete: 'warning',
  failed: 'negative',
};

const FETCH_ERROR = "Couldn't load the billing check.";

export default defineComponent({
  name: 'BillingIntegrity',
  mixins: [formatMixin],
  data() {
    return {
      status: null as IntegrityStatus | null,
      issues: [] as IntegrityIssue[],
      loading: false,
    };
  },
  computed: {
    severities(): Severity[] {
      return SEVERITIES;
    },
    banners(): StatusBanner[] {
      return this.status ? statusBanners(this.status) : [];
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
      this.$axios
        .get('/api/admin/billing/integrity/issues/')
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
