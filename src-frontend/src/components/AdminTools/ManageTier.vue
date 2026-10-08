<template>
  <div class="row q-gutter-md">
    <q-card>
      <q-card-section class="row items-center">
        <span class="q-ml-sm">{{ $t('menuLink.manageTier') }}</span>
      </q-card-section>

      <q-card-actions align="right">
        <q-form ref="formRef" @submit="submitTier()">
          <q-input
            v-model="form.name"
            outlined
            :debounce="debounceLength"
            :label="$t('form.name')"
            :rules="[
              (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
            ]"
          />

          <q-input
            v-model="form.description"
            outlined
            :debounce="debounceLength"
            :label="$t('form.description')"
            :rules="[
              (val) => validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
            ]"
          />

          <q-checkbox
            v-model="form.visible"
            :label="$t('form.visibleToMembers')"
          />

          <q-checkbox v-model="form.featured" :label="$t('form.featured')" />

          <q-banner v-if="form.success" class="bg-positive text-white q-my-md">
            {{ $t('form.saved') }}
          </q-banner>

          <q-banner v-if="form.error" class="bg-negative text-white q-my-md">
            {{ $t('form.error') }}
          </q-banner>

          <q-card-actions align="right" class="text-primary">
            <q-btn
              color="negative"
              :label="$t('button.remove')"
              :disable="form.loading"
              @click="removeTier()"
            />
            <q-btn
              color="primary"
              :label="$t('button.submit')"
              :loading="form.loading"
              :disable="form.loading"
              type="submit"
            />
          </q-card-actions>
        </q-form>
      </q-card-actions>
    </q-card>
    <q-card>
      <q-card-section class="row items-center">
        <span class="q-ml-sm">{{ $t('paymentPlans.title') }}</span>
      </q-card-section>

      <q-card-section class="row items-center q-pt-none">
        <q-table
          flat
          @row-click="managePlan"
          :rows="plans"
          :columns="[
            { name: 'name', label: 'Name', field: 'name', sortable: true },
            {
              name: 'visible',
              label: 'Visible',
              field: 'visible',
              sortable: true,
            },
            {
              name: 'featured',
              label: 'Featured',
              field: 'featured',
              sortable: true,
            },
            {
              name: 'cost',
              label: 'Cost',
              field: 'cost',
              sortable: true,
              format: (val) => `$${val}`,
            },
            {
              name: 'interval',
              label: 'Interval',
              field: 'interval',
              sortable: true,
              format: (val, row) =>
                `${row.intervalCount} ${row.interval}${
                  row.intervalCount > 1 ? 's' : ''
                }`,
            },
          ]"
          row-key="id"
          :filter="filter"
          v-model:pagination="pagination"
          :grid="$q.screen.xs"
          :no-data-label="$t('paymentPlans.nodata')"
        >
          <template v-slot:top-right>
            <q-input
              v-model="filter"
              outlined
              dense
              debounce="300"
              placeholder="Search"
            >
              <template v-slot:append>
                <q-icon :name="icons.search" />
              </template>
            </q-input>
          </template>
          <template v-slot:top-left>
            <q-btn
              @click="addPlanDialog = true"
              round
              color="primary"
              :icon="icons.addAlternative"
            >
              <q-tooltip :delay="500">{{ $t('tiers.add') }}</q-tooltip>
            </q-btn>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <q-dialog v-model="addPlanDialog" persistent>
      <q-card>
        <q-card-section class="row items-center">
          <span class="q-ml-sm">{{ $t('paymentPlans.add') }}</span>
        </q-card-section>

        <q-card-actions align="right">
          <q-form ref="formRef" @submit="submitPlanForm()">
            <div class="row q-col-gutter-sm">
              <q-input
                class="col-sm-6 col-xs-12"
                v-model="planForm.name"
                outlined
                :debounce="debounceLength"
                :label="$t('form.name')"
                :rules="[
                  (val) =>
                    validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                ]"
                :disable="form.success"
              />
              <q-input
                class="col-sm-6 col-xs-12"
                v-model="planForm.description"
                outlined
                :debounce="debounceLength"
                :label="$t('paymentPlans.description')"
                :disable="form.success"
              />
              <q-input
                class="col-sm-6 col-xs-12"
                v-model="planForm.currency"
                outlined
                :debounce="debounceLength"
                :label="$t('form.currency')"
                :rules="[
                  (val) =>
                    validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                ]"
                :disable="form.success"
              />
              <q-input
                class="col-sm-6 col-xs-12"
                v-model="planForm.costString"
                outlined
                :debounce="debounceLength"
                :label="$t('form.cost')"
                :rules="[
                  (val) =>
                    validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                ]"
                :disable="form.success"
                prefix="$"
              />

              <q-checkbox
                class="col-sm-6 col-xs-12"
                v-model="planForm.visible"
                :label="$t('form.visibleToMembers')"
              />

              <q-card-section class="col-12">
                <span class="q-ml-sm">{{
                  $t('paymentPlans.recurringDescription')
                }}</span>
              </q-card-section>

              <q-input
                class="col-sm-6 col-xs-12"
                v-model="planForm.intervalCount"
                outlined
                :debounce="debounceLength"
                :label="$t('form.intervalCount')"
                :rules="[
                  (val) =>
                    validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                ]"
                :disable="form.success"
              />
              <q-select
                outlined
                class="col-sm-6 col-xs-12"
                v-model="planForm.interval"
                :debounce="debounceLength"
                :label="$t('form.interval')"
                :rules="[
                  (val) =>
                    validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                ]"
                :disable="form.success"
                :options="intervalOptions"
                emit-value
                options-dense
                map-options
              />
            </div>

            <q-banner
              v-if="planForm.success"
              class="bg-positive text-white q-my-md"
            >
              {{ $t('paymentPlans.success') }}
            </q-banner>

            <q-banner
              v-if="planForm.error"
              class="bg-negative text-white q-my-md"
            >
              {{ $t('paymentPlans.fail') }}
            </q-banner>

            <q-card-actions v-if="!planForm.success" class="text-primary">
              <q-space />
              <q-btn
                v-close-popup
                flat
                :label="$t('button.cancel')"
                :disable="planForm.loading"
              />
              <q-btn
                color="primary"
                :label="$t('button.submit')"
                :loading="planForm.loading"
                :disable="planForm.loading"
                type="submit"
              />
            </q-card-actions>

            <q-card-actions v-else align="right" class="text-primary">
              <q-btn v-close-popup flat :label="$t('button.close')" />
            </q-card-actions>
          </q-form>
        </q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog
      v-model="editPlanDialog"
      persistent
      @hide="stopPriceChangePolling()"
    >
      <q-card style="min-width: 400px">
        <q-card-section class="row items-center">
          <span class="q-ml-sm">{{ $t('paymentPlans.edit') }}</span>
        </q-card-section>

        <q-card-actions align="right">
          <q-form @submit="submitEditPlanForm()" v-if="editPlan">
            <div class="row q-col-gutter-sm">
              <q-input
                class="col-12"
                v-model="editPlan.name"
                outlined
                :debounce="debounceLength"
                :label="$t('form.name')"
                :rules="[
                  (val) =>
                    validateNotEmpty(val) || $t('validation.cannotBeEmpty'),
                ]"
              />
              <q-input
                class="col-12"
                v-model="editPlan.description"
                outlined
                :debounce="debounceLength"
                :label="$t('paymentPlans.description')"
              />
              <q-checkbox
                class="col-12"
                v-model="editPlan.visible"
                :label="$t('form.visibleToMembers')"
              />
            </div>

            <q-banner
              v-if="editPlanForm.success"
              class="bg-positive text-white q-my-md"
            >
              {{ $t('form.saved') }}
            </q-banner>
            <q-banner
              v-if="editPlanForm.error"
              class="bg-negative text-white q-my-md"
            >
              {{ $t('form.error') }}
            </q-banner>

            <q-card-actions class="text-primary">
              <q-btn
                color="negative"
                :label="$t('button.remove')"
                :disable="editPlanForm.loading"
                @click="removePlan()"
              />
              <q-space />
              <q-btn
                v-close-popup
                flat
                :label="$t('button.cancel')"
                :disable="editPlanForm.loading"
              />
              <q-btn
                color="primary"
                :label="$t('button.submit')"
                :loading="editPlanForm.loading"
                :disable="editPlanForm.loading"
                type="submit"
              />
            </q-card-actions>
          </q-form>
        </q-card-actions>

        <q-separator />

        <q-card-section v-if="editPlan" style="max-width: 500px">
          <div class="text-subtitle1">
            {{ $t('paymentPlans.price.title') }}
          </div>
          <p>
            {{
              $t('paymentPlans.price.current', {
                amount: formatPlanAmount(
                  Math.round(editPlan.cost * 100),
                  editPlan.currency
                ),
              })
            }}
          </p>

          <template v-if="showPriceChange && priceChange">
            <q-banner
              :class="priceChangeBannerClass"
              class="text-white q-mb-md"
            >
              {{ priceChangeStatusText }}
              <div v-if="priceChange.error">{{ priceChange.error }}</div>
            </q-banner>
            <q-linear-progress
              v-if="priceChangeInFlight"
              indeterminate
              class="q-mb-md"
            />
            <q-list
              v-if="priceChange.failures.length"
              dense
              bordered
              class="q-mb-md"
            >
              <q-item-label header>
                {{ $t('paymentPlans.price.failuresTitle') }}
              </q-item-label>
              <q-item
                v-for="failure in priceChange.failures"
                :key="failure.subscription"
              >
                <q-item-section>
                  <q-item-label>
                    {{ failure.member || failure.customer }}
                  </q-item-label>
                  <q-item-label caption>
                    {{ failure.subscription }}: {{ failure.error }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
            <q-btn
              v-if="priceChangeResumable"
              color="primary"
              class="q-mb-md"
              :label="$t('paymentPlans.price.resume')"
              :loading="priceForm.loading"
              :disable="priceForm.loading"
              @click="resumePriceChange()"
            />
          </template>

          <q-form
            v-if="canChangePrice"
            class="row q-col-gutter-sm items-start"
            @submit="confirmPriceChange()"
          >
            <q-input
              class="col-sm-8 col-xs-12"
              v-model="priceForm.costString"
              outlined
              :label="$t('paymentPlans.price.new')"
              prefix="$"
              :rules="[
                (val) =>
                  validPriceString(val) || $t('paymentPlans.invalidCost'),
              ]"
              :disable="priceForm.loading"
            />
            <div class="col-sm-4 col-xs-12">
              <q-btn
                color="primary"
                type="submit"
                :label="$t('paymentPlans.price.change')"
                :loading="priceForm.loading"
                :disable="priceForm.loading"
              />
            </div>
          </q-form>

          <q-banner v-if="priceForm.error" class="bg-negative text-white">
            {{ priceForm.error }}
          </q-banner>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { useStore } from 'vuex';
import { AxiosResponse } from 'axios';
import { api } from 'boot/axios';
import icons from '../../icons';
import formatMixin from '../../mixins/formatMixin';
import formMixin from '../../mixins/formMixin';

interface PriceChangeFailure {
  subscription: string;
  customer: string | null;
  member: string | null;
  memberId: number | null;
  error: string;
}

interface PriceChange {
  id: number;
  oldCost: number;
  newCost: number;
  currency: string;
  status: 'pending' | 'running' | 'completed' | 'partial' | 'interrupted';
  runs: number;
  migratedCount: number;
  remainingCount: number;
  failures: PriceChangeFailure[];
  error: string;
  // ISO 8601 UTC
  updatedAt: string;
}

const PRICE_CHANGE_POLL_MS = 2000;
// Mirrors the backend: a queued job no worker has picked up, or a run that
// stopped saving progress, can be resumed after this long.
const PENDING_RESUMABLE_AFTER_MS = 60 * 1000;
const RUNNING_RESUMABLE_AFTER_MS = 10 * 60 * 1000;

export default defineComponent({
  name: 'ManageTier',
  mixins: [formatMixin, formMixin],
  setup() {
    const store = useStore();
    const getTiers = () => store.dispatch('adminTools/getTiers');

    return {
      getTiers,
    };
  },
  data() {
    return {
      plans: [],
      form: {
        loading: false,
        error: false,
        success: false,
        name: '',
        description: '',
        visible: false,
        featured: false,
      },
      planForm: {
        loading: false,
        error: false,
        success: false,
        name: '',
        description: '',
        memberTier: '',
        stripeId: '',
        visible: true,
        currency: 'aud',
        costString: '',
        cost: 0,
        intervalCount: 1,
        interval: 'month',
      },
      addPlanDialog: false,
      editPlanDialog: false,
      editPlan: null as {
        id: number;
        name: string;
        description: string;
        visible: boolean;
        cost: number;
        currency: string;
        stripeId: string;
        memberTier: number;
        intervalCount: number;
        interval: string;
      } | null,
      editPlanForm: {
        loading: false,
        error: false,
        success: false,
      },
      priceChange: null as PriceChange | null,
      // Show a completed change only if it finished while the dialog was open.
      priceChangeStartedHere: false,
      subscriptionCount: 0,
      // After a resume, the job keeps its last run's status until a worker
      // starts the next run; this is that last run's number.
      awaitingRunAfter: null as number | null,
      resumedAt: 0,
      priceChangePoll: null as ReturnType<typeof setInterval> | null,
      priceForm: {
        loading: false,
        error: '',
        costString: '',
      },
      filter: '',
      pagination: {
        sortBy: 'name',
        descending: true,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        rowsPerPage: (this as any).$q.screen.xs ? 3 : 10,
      },
    };
  },
  mounted() {
    this.getTier();
    this.getPlans();
  },
  beforeUnmount() {
    this.stopPriceChangePolling();
  },
  computed: {
    icons() {
      return icons;
    },
    priceChangeStatus(): string {
      if (this.awaitingRunAfter !== null) return 'pending';
      return this.priceChange?.status ?? '';
    },
    priceChangeInFlight(): boolean {
      return ['pending', 'running'].includes(this.priceChangeStatus);
    },
    showPriceChange(): boolean {
      if (!this.priceChange) return false;
      return (
        this.priceChange.status !== 'completed' || this.priceChangeStartedHere
      );
    },
    canChangePrice(): boolean {
      return !this.priceChange || this.priceChange.status === 'completed';
    },
    priceChangeResumable(): boolean {
      const change = this.priceChange;
      if (!change) return false;
      const status = this.priceChangeStatus;
      if (['partial', 'interrupted'].includes(status)) return true;
      const lastActivity =
        this.awaitingRunAfter !== null
          ? this.resumedAt
          : Date.parse(change.updatedAt);
      const idle = Date.now() - lastActivity;
      if (status === 'pending') return idle > PENDING_RESUMABLE_AFTER_MS;
      if (status === 'running') return idle > RUNNING_RESUMABLE_AFTER_MS;
      return false;
    },
    priceChangeBannerClass(): string {
      switch (this.priceChangeStatus) {
        case 'completed':
          return 'bg-positive';
        case 'partial':
        case 'interrupted':
          return 'bg-negative';
        default:
          return 'bg-info';
      }
    },
    priceChangeStatusText(): string {
      const change = this.priceChange;
      if (!change) return '';
      return this.$t(`paymentPlans.price.status.${this.priceChangeStatus}`, {
        old: this.formatPlanAmount(change.oldCost, change.currency),
        new: this.formatPlanAmount(change.newCost, change.currency),
        migrated: change.migratedCount,
        remaining: change.remainingCount,
      });
    },
  },
  methods: {
    getTier() {
      this.planForm.memberTier = this.$route.params.planId.toString();
      api
        .get(`/api/admin/tiers/${this.$route.params.planId}/`)
        .then((response: AxiosResponse) => {
          this.form.name = response.data.name;
          this.form.description = response.data.description;
          this.form.visible = response.data.visible;
          this.form.featured = response.data.featured;
        })
        .catch((error) => {
          if (error.response.status === 404) {
            this.$router.push({ name: 'Error404' });
            return;
          }
          this.$q.dialog({
            title: this.$tc('error.error'),
            message: this.$tc('error.requestFailed'),
          });
        });
    },
    removeTier() {
      this.$q
        .dialog({
          title: this.$tc('confirmAction'),
          message: this.$tc('confirmRemove'),
          cancel: true,
          persistent: true,
        })
        .onOk(() => {
          api
            .delete(`/api/admin/tiers/${this.$route.params.planId}/`)
            .then(() => {
              this.$router.go(-1);
            })
            .catch(() => {
              this.$q.dialog({
                title: this.$tc('error.error'),
                message: this.$tc('error.requestFailed'),
              });
            });
        });
    },
    submitTier() {
      this.form.loading = true;
      this.form.error = false;
      this.form.success = false;
      api
        .put(`/api/admin/tiers/${this.$route.params.planId}/`, this.form)
        .then(() => {
          this.getTiers();
          this.form.success = true;
          this.form.error = false;
        })
        .catch(() => {
          this.form.error = true;
          this.form.success = false;
        })
        .finally(() => (this.form.loading = false));
    },
    submitPlanForm() {
      this.planForm.loading = true;
      this.planForm.error = false;
      this.planForm.success = false;
      this.planForm.cost = parseFloat(this.planForm.costString) * 100;
      api
        .post('/api/admin/plans/', this.planForm)
        .then(() => {
          this.getPlans();
          this.planForm.success = true;
          this.planForm.error = false;
          this.addPlanDialog = false;
          this.resetPlanForm();
        })
        .catch(() => {
          this.planForm.success = false;
          this.planForm.error = true;
        })
        .finally(() => (this.planForm.loading = false));
    },
    getPlans() {
      api
        .get(`/api/admin/tiers/${this.$route.params.planId}/plans/`)
        .then((response: AxiosResponse) => {
          this.plans = response.data;
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$tc('error.error'),
            message: this.$tc('error.requestFailed'),
          });
        });
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    managePlan(evt: InputEvent, row: any) {
      this.editPlan = { ...row };
      this.editPlanForm = { loading: false, error: false, success: false };
      this.priceChange = null;
      this.priceChangeStartedHere = false;
      this.awaitingRunAfter = null;
      this.priceForm = { loading: false, error: '', costString: '' };
      this.editPlanDialog = true;
      this.getPriceChanges(row.id);
    },
    formatPlanAmount(cents: number, currency: string) {
      return `${(cents / 100).toFixed(2)} ${currency.toUpperCase()}`;
    },
    validPriceString(val: string) {
      return /^\d+(\.\d{1,2})?$/.test(val?.trim() ?? '') && parseFloat(val) > 0;
    },
    priceChangeErrorText(error: {
      response?: { data?: { message?: string } };
    }) {
      const key = error?.response?.data?.message;
      return key && this.$te(key)
        ? this.$tc(key)
        : this.$tc('error.requestFailed');
    },
    getPriceChanges(planId: number) {
      api
        .get(`/api/admin/plans/${planId}/price-changes/`)
        .then((response: AxiosResponse) => {
          this.subscriptionCount = response.data.subscriptionCount;
          this.setPriceChange(response.data.priceChanges[0] ?? null);
        })
        .catch(() => {
          this.priceForm.error = this.$tc('error.requestFailed');
        });
    },
    setPriceChange(change: PriceChange | null) {
      this.priceChange = change;
      if (
        change &&
        this.awaitingRunAfter !== null &&
        change.runs > this.awaitingRunAfter
      ) {
        this.awaitingRunAfter = null;
      }
      if (this.priceChangeInFlight) {
        this.startPriceChangePolling();
      } else {
        this.stopPriceChangePolling();
      }
    },
    startPriceChangePolling() {
      if (this.priceChangePoll) return;
      this.priceChangePoll = setInterval(() => {
        if (!this.priceChange) return;
        api
          .get(`/api/admin/price-changes/${this.priceChange.id}/`)
          .then((response: AxiosResponse) => this.setPriceChange(response.data))
          .catch(() => {
            // Keep polling; a blip shouldn't drop the progress view.
          });
      }, PRICE_CHANGE_POLL_MS);
    },
    stopPriceChangePolling() {
      if (this.priceChangePoll) clearInterval(this.priceChangePoll);
      this.priceChangePoll = null;
    },
    confirmPriceChange() {
      if (!this.editPlan) return;
      const cost = Math.round(parseFloat(this.priceForm.costString) * 100);
      this.$q
        .dialog({
          title: this.$tc('paymentPlans.price.confirmTitle'),
          message: this.$t('paymentPlans.price.confirmMessage', {
            amount: this.formatPlanAmount(cost, this.editPlan.currency),
            count: this.subscriptionCount,
          }),
          cancel: true,
          persistent: true,
        })
        .onOk(() => this.submitPriceChange(cost));
    },
    submitPriceChange(cost: number) {
      if (!this.editPlan) return;
      this.priceForm.loading = true;
      this.priceForm.error = '';
      api
        .post(`/api/admin/plans/${this.editPlan.id}/price-changes/`, { cost })
        .then((response: AxiosResponse) => {
          this.priceChangeStartedHere = true;
          this.priceForm.costString = '';
          // New signups pay the new price from now on.
          if (this.editPlan) this.editPlan.cost = cost / 100;
          this.setPriceChange(response.data.priceChange);
          this.getPlans();
        })
        .catch((error) => {
          this.priceForm.error = this.priceChangeErrorText(error);
          // 409: another change is unfinished; show it so it can be resumed.
          const existing = error?.response?.data?.priceChange;
          if (existing) this.setPriceChange(existing);
        })
        .finally(() => (this.priceForm.loading = false));
    },
    resumePriceChange() {
      if (!this.priceChange) return;
      this.priceForm.loading = true;
      this.priceForm.error = '';
      api
        .post(`/api/admin/price-changes/${this.priceChange.id}/resume/`)
        .then((response: AxiosResponse) => {
          this.priceChangeStartedHere = true;
          this.awaitingRunAfter = response.data.priceChange.runs;
          this.resumedAt = Date.now();
          this.setPriceChange(response.data.priceChange);
        })
        .catch((error) => {
          this.priceForm.error = this.priceChangeErrorText(error);
        })
        .finally(() => (this.priceForm.loading = false));
    },
    submitEditPlanForm() {
      if (!this.editPlan) return;
      this.editPlanForm.loading = true;
      this.editPlanForm.error = false;
      this.editPlanForm.success = false;
      const payload = {
        ...this.editPlan,
        cost: Math.round(this.editPlan.cost * 100),
      };
      api
        .put(`/api/admin/plans/${this.editPlan.id}/`, payload)
        .then(() => {
          this.getPlans();
          this.editPlanForm.success = true;
          this.editPlanForm.error = false;
        })
        .catch(() => {
          this.editPlanForm.error = true;
          this.editPlanForm.success = false;
        })
        .finally(() => (this.editPlanForm.loading = false));
    },
    removePlan() {
      this.$q
        .dialog({
          title: this.$tc('confirmAction'),
          message: this.$tc('confirmRemove'),
          cancel: true,
          persistent: true,
        })
        .onOk(() => {
          api
            .delete(`/api/admin/plans/${this.editPlan.id}/`)
            .then(() => {
              this.editPlanDialog = false;
              this.getPlans();
            })
            .catch(() => {
              this.$q.dialog({
                title: this.$tc('error.error'),
                message: this.$tc('error.requestFailed'),
              });
            });
        });
    },
    resetForm() {
      this.form = {
        loading: false,
        error: false,
        success: false,
        name: '',
        description: '',
        visible: false,
        featured: false,
      };
    },
    resetPlanForm() {
      this.planForm = {
        loading: false,
        error: false,
        success: false,
        name: '',
        description: '',
        memberTier: this.$route.params.planId.toString(),
        stripeId: '',
        visible: true,
        currency: 'aud',
        costString: '',
        cost: 0,
        intervalCount: 1,
        interval: 'month',
      };
    },
  },
});
</script>
