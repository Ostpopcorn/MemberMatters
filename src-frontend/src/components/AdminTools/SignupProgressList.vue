<template>
  <div style="max-width: 100%">
    <p class="text-grey-7 q-mb-sm">{{ $t('signupProgress.description') }}</p>

    <q-table
      :rows="filteredMembers"
      :columns="columns"
      :no-data-label="$t('adminTools.noMembers')"
      row-key="id"
      v-model:pagination="pagination"
      :loading="loading"
      :grid="grid"
      class="full-width"
    >
      <template v-slot:top>
        <div class="full-width">
          <div class="row items-start justify-between">
            <div class="row items-center q-gutter-sm q-mb-sm">
              <q-select
                v-model="stateFilter"
                outlined
                dense
                emit-value
                map-options
                style="min-width: 140px"
                :options="stateFilterOptions"
                :label="$t('adminTools.filterOptions')"
              />

              <q-btn-dropdown
                v-if="steps.length"
                outline
                color="primary"
                :icon="icons.filter"
                :label="stepsFilterLabel"
              >
                <q-list class="q-py-sm">
                  <q-item v-for="step in steps" :key="step" class="q-py-md">
                    <q-item-section>
                      <q-item-label class="text-body1 q-mb-sm">
                        <q-icon :name="stepIcon(step)" class="q-mr-sm" />
                        {{ stepLabel(step) }}
                      </q-item-label>
                      <!-- Icon sits in the label, not an avatar column, so the
                           buttons get the full menu width on a phone. -->
                      <q-btn-toggle
                        :model-value="stepFilters[step] || 'any'"
                        no-caps
                        unelevated
                        class="step-toggle"
                        :padding="$q.screen.xs ? '6px 8px' : '6px 12px'"
                        color="grey-3"
                        text-color="grey-9"
                        toggle-color="primary"
                        toggle-text-color="white"
                        :options="stepFilterOptions(step)"
                        @update:model-value="setStepFilter(step, $event)"
                      />
                    </q-item-section>
                  </q-item>

                  <q-separator />

                  <q-item
                    v-close-popup
                    clickable
                    :disable="!activeStepFilters.length"
                    @click="stepFilters = {}"
                  >
                    <q-item-section avatar>
                      <q-icon :name="icons.close" />
                    </q-item-section>
                    <q-item-section>
                      {{ $t('signupProgress.clearStepFilters') }}
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-btn-dropdown>

              <card-sort-control
                v-if="grid"
                v-model:pagination="pagination"
                :columns="columns"
              />
            </div>

            <member-export-buttons
              :members="filteredMembers"
              :csv-columns="csvColumns"
              filename="signup-progress-export.csv"
            />
          </div>

          <!-- What the table and exports are narrowed to, at a glance. -->
          <div
            v-if="activeStepFilters.length"
            class="row items-center q-gutter-sm q-mb-sm"
          >
            <q-chip
              v-for="[step, state] in activeStepFilters"
              :key="step"
              removable
              class="q-px-md"
              color="primary"
              text-color="white"
              :icon="stepIcon(step)"
              @remove="setStepFilter(step, 'any')"
            >
              {{ stepLabel(step) }}: {{ stepStateLabel(state) }}
            </q-chip>
          </div>
        </div>
      </template>

      <template v-slot:body="props">
        <q-tr
          :props="props"
          class="cursor-pointer"
          @click="goToMember(props.row)"
        >
          <q-td key="member" :props="props">
            {{ props.row.name.full || $t('error.noValue') }}
            <span v-if="props.row.screenName" class="text-grey-7">
              ({{ props.row.screenName }})
            </span>
            <div class="text-caption text-grey-7">{{ props.row.email }}</div>
          </q-td>

          <q-td key="state" :props="props">
            <q-badge :color="memberStateColor(props.row.state)">
              {{ $t(`adminTools.memberStatusString.${props.row.state}`) }}
            </q-badge>
          </q-td>

          <q-td
            v-for="step in steps"
            :key="`step_${step}`"
            :props="props"
            class="text-center"
          >
            <q-icon
              :name="iconForStep(step, props.row)"
              :color="colorForStep(step, props.row)"
              size="sm"
            >
              <q-tooltip>{{ tooltipForStep(step, props.row) }}</q-tooltip>
            </q-icon>
          </q-td>

          <q-td key="registered" :props="props">
            {{ formatDate(props.row.registrationDate) }}
          </q-td>

          <q-td key="lastSeen" :props="props">
            {{
              props.row.lastSeen
                ? formatDate(props.row.lastSeen)
                : $t('error.noValue')
            }}
          </q-td>
        </q-tr>
      </template>

      <template v-slot:item="props">
        <div class="q-pa-xs col-xs-12 col-sm-6 col-md-4 col-lg-3">
          <member-summary-card
            :member="props.row"
            @click="goToMember(props.row)"
          >
            <q-list dense class="q-mb-sm">
              <q-item
                v-for="step in steps"
                :key="step"
                dense
                class="q-px-none step-item"
              >
                <q-item-section avatar class="step-icon">
                  <q-icon
                    :name="iconForStep(step, props.row)"
                    :color="colorForStep(step, props.row)"
                    size="xs"
                  />
                </q-item-section>
                <q-item-section>{{ stepLabel(step) }}</q-item-section>
                <q-item-section side class="text-caption">
                  {{ tooltipForStep(step, props.row) }}
                </q-item-section>
              </q-item>
            </q-list>

            <div class="text-caption text-grey-7">
              {{ $t('adminTools.registrationDate') }}:
              {{ formatDate(props.row.registrationDate, false) }}
            </div>
            <div class="text-caption text-grey-7">
              {{ $t('adminTools.lastSeen') }}:
              {{
                props.row.lastSeen
                  ? formatDate(props.row.lastSeen, false)
                  : $t('error.noValue')
              }}
            </div>
          </member-summary-card>
        </div>
      </template>
    </q-table>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { mapGetters } from 'vuex';
import icons from '@icons';
import formatMixin, { formatDate } from '@mixins/formatMixin';
import CardSortControl from '@components/AdminTools/CardSortControl.vue';
import MemberExportButtons from '@components/AdminTools/MemberExportButtons.vue';
import MemberSummaryCard from '@components/AdminTools/MemberSummaryCard.vue';
import { MemberProfile } from 'types/member';
import { memberMatchesQuery } from '../../utils/fuzzySearch';
import { CsvColumn } from '../../utils/memberExport';
import { memberStateColor } from '../../utils/memberStatus';
import {
  enabledSignupSteps,
  matchesStepFilters,
  nextSignupStep,
  signupStepState,
  SignupStep,
  SignupStepFilters,
  SignupStepStateName,
} from '../../utils/signupSteps';

interface SignupRow extends MemberProfile {
  requiredSteps: string[];
}

const STEP_LABEL_KEYS: Record<SignupStep, string> = {
  payment: 'membershipStatusCard.payment',
  terms: 'signup.termsAcceptance',
  induction: 'signup.induction',
  accessCard: 'signup.accessCard',
};

const STEP_STATE_LABEL_KEYS: Record<SignupStepStateName, string> = {
  complete: 'signupProgress.complete',
  pending: 'signupProgress.pending',
  outstanding: 'signupProgress.required',
};

// Noob/inactive members and how far through signup each one is. The search
// query comes from the parent so it can be shared with the members tab.
export default defineComponent({
  name: 'SignupProgressList',
  components: { CardSortControl, MemberExportButtons, MemberSummaryCard },
  mixins: [formatMixin],
  props: {
    grid: {
      type: Boolean,
      default: false,
    },
    search: {
      type: String,
      default: '',
    },
  },
  data() {
    return {
      members: [] as SignupRow[],
      loading: false,
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
    icons() {
      return icons;
    },
    stateFilter: {
      get(): string {
        return this.$store.getters['adminTools/signupState'];
      },
      set(value: string) {
        this.$store.commit('adminTools/setSignupState', value);
      },
    },
    stepFilters: {
      get(): SignupStepFilters {
        return this.$store.getters['adminTools/signupStepFilters'];
      },
      set(value: SignupStepFilters) {
        this.$store.commit('adminTools/setSignupStepFilters', value);
      },
    },
    pagination: {
      get() {
        return this.$store.getters['adminTools/signupPagination'];
      },
      set(value: object) {
        this.$store.commit('adminTools/setSignupPagination', value);
      },
    },
    steps(): SignupStep[] {
      return enabledSignupSteps(this.features);
    },
    // Only filters on enabled steps count; the rest are ignored anyway.
    activeStepFilters(): [SignupStep, SignupStepStateName][] {
      return this.steps
        .filter((step) => this.stepFilters[step])
        .map((step) => [step, this.stepFilters[step] as SignupStepStateName]);
    },
    stepsFilterLabel(): string {
      const label = this.$t('signupProgress.stepsFilter');
      const count = this.activeStepFilters.length;
      return count ? `${label} (${count})` : label;
    },
    stateFilterOptions() {
      return [
        { label: this.$t('adminTools.all'), value: 'all' },
        { label: this.$t('adminTools.new'), value: 'noob' },
        { label: this.$t('adminTools.inactive'), value: 'inactive' },
      ];
    },
    filteredMembers(): SignupRow[] {
      return this.members.filter(
        (member) =>
          (this.stateFilter === 'all' || member.state === this.stateFilter) &&
          matchesStepFilters(
            this.features,
            this.stepFilters,
            member.requiredSteps,
            member.subscriptionStatus
          ) &&
          memberMatchesQuery(member, this.search)
      );
    },
    columns() {
      return [
        {
          name: 'member',
          label: this.$t('tableHeading.name'),
          field: (row: SignupRow) =>
            `${row.name.full} ${row.screenName} ${row.email}`,
          align: 'left' as const,
          sortable: true,
        },
        {
          name: 'state',
          label: this.$t('tableHeading.status'),
          field: 'state',
          align: 'left' as const,
          sortable: true,
        },
        ...this.steps.map((step) => ({
          name: `step_${step}`,
          label: this.stepLabel(step),
          field: step,
          align: 'center' as const,
          sortable: false,
        })),
        {
          name: 'registered',
          label: this.$t('adminTools.registrationDate'),
          field: 'registrationDate',
          align: 'left' as const,
          sortable: true,
        },
        {
          name: 'lastSeen',
          label: this.$t('adminTools.lastSeen'),
          field: 'lastSeen',
          align: 'left' as const,
          sortable: true,
        },
      ];
    },
    csvColumns(): CsvColumn<SignupRow>[] {
      return [
        { header: this.$t('tableHeading.name'), value: (m) => m.name.full },
        {
          header: this.$t('tableHeading.screenName'),
          value: (m) => m.screenName,
        },
        { header: this.$t('tableHeading.email'), value: (m) => m.email },
        {
          header: this.$t('tableHeading.status'),
          value: (m) => this.$t(`adminTools.memberStatusString.${m.state}`),
        },
        {
          header: this.$t('tableHeading.subscriptionStatus'),
          value: (m) =>
            this.$t(
              `adminTools.subscriptionStatusString.${m.subscriptionStatus}`
            ),
        },
        ...this.steps.map((step) => ({
          header: this.stepLabel(step),
          value: (m: SignupRow) =>
            this.stepStateLabel(
              signupStepState(step, m.requiredSteps, m.subscriptionStatus)
            ),
        })),
        {
          header: this.$t('adminTools.registrationDate'),
          value: (m) => formatDate(m.registrationDate as unknown as Date),
        },
        {
          header: this.$t('adminTools.lastSeen'),
          value: (m) =>
            m.lastSeen ? formatDate(m.lastSeen as unknown as Date) : '',
        },
      ];
    },
  },
  mounted() {
    this.getMembers();
  },
  methods: {
    memberStateColor,
    getMembers() {
      this.loading = true;
      this.$axios
        .get('/api/admin/signup-progress/')
        .then((response) => {
          this.members = response.data;
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.loading = false;
        });
    },
    goToMember(row: SignupRow) {
      this.$router.push({ name: 'manageMember', params: { memberId: row.id } });
    },
    stepLabel(step: SignupStep): string {
      return this.$t(STEP_LABEL_KEYS[step]);
    },
    stepStateLabel(state: SignupStepStateName): string {
      return this.$t(STEP_STATE_LABEL_KEYS[state]);
    },
    stepIcon(step: SignupStep): string {
      return step === 'payment' ? icons.billing : icons[step];
    },
    // Only payment can be pending.
    stepFilterOptions(step: SignupStep) {
      const states: SignupStepStateName[] =
        step === 'payment'
          ? ['complete', 'pending', 'outstanding']
          : ['complete', 'outstanding'];
      return [
        { label: this.$t('signupProgress.any'), value: 'any' },
        ...states.map((state) => ({
          label: this.stepStateLabel(state),
          value: state,
        })),
      ];
    },
    setStepFilter(step: SignupStep, value: SignupStepStateName | 'any') {
      const filters = { ...this.stepFilters };
      if (value === 'any') delete filters[step];
      else filters[step] = value;
      this.stepFilters = filters;
    },
    nextStepFor(row: SignupRow): SignupStep | null {
      return nextSignupStep(
        this.features,
        row.requiredSteps,
        row.subscriptionStatus
      );
    },
    iconForStep(step: SignupStep, row: SignupRow): string {
      const state = signupStepState(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (state === 'complete') return icons.success;
      if (state === 'pending') return icons.clock;
      if (this.nextStepFor(row) === step) return icons.crosshairs;
      return icons.minus;
    },
    colorForStep(step: SignupStep, row: SignupRow): string {
      const state = signupStepState(
        step,
        row.requiredSteps,
        row.subscriptionStatus
      );
      if (state === 'complete') return 'positive';
      if (state === 'pending') return 'warning';
      if (this.nextStepFor(row) === step) return 'blue';
      return 'grey-4';
    },
    tooltipForStep(step: SignupStep, row: SignupRow): string {
      if (this.nextStepFor(row) === step) {
        return this.$t('signupProgress.nextStep');
      }
      return this.stepStateLabel(
        signupStepState(step, row.requiredSteps, row.subscriptionStatus)
      );
    },
  },
});
</script>

<style scoped lang="scss">
// Quasar caps the menu at the space beside the button; wrap rather than
// clip if the options still don't fit.
.step-toggle {
  flex-wrap: wrap;
}

.step-item {
  min-height: 26px;
}

.step-icon {
  min-width: 28px;
}
</style>
