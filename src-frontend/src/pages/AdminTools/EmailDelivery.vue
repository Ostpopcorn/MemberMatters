<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">Email Delivery</div>
    <p class="text-grey-7">
      Checks whether MemberMatters can send email right now, and sends a test
      email to the admin address.
    </p>

    <q-card flat bordered class="q-mb-lg">
      <q-card-section class="row items-center no-wrap">
        <div class="text-h6 col">Delivery status</div>
        <q-btn
          flat
          dense
          color="primary"
          :icon="icons.sync"
          label="Re-check"
          :loading="statusLoading"
          @click="loadStatus"
        />
      </q-card-section>
      <q-separator />

      <div v-if="statusLoading && !checks.length" class="q-pa-lg text-center">
        <q-spinner size="3em" />
      </div>
      <q-banner v-else-if="statusError" class="text-negative">
        {{ statusError }}
      </q-banner>
      <q-list v-else separator>
        <q-item v-for="check in checks" :key="check.key">
          <q-item-section avatar>
            <q-icon
              :name="statusIcons[check.status].icon"
              :color="statusIcons[check.status].color"
            />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ check.label }}</q-item-label>
            <!-- On phones the value sits under the label instead of beside it. -->
            <q-item-label class="xs check-value text-grey-8">
              {{ check.value }}
            </q-item-label>
            <q-item-label v-if="check.detail" caption>
              {{ check.detail }}
            </q-item-label>
          </q-item-section>
          <q-item-section side class="gt-xs check-value check-value--side">
            {{ check.value }}
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>

    <q-card flat bordered>
      <q-card-section>
        <div class="text-h6">Test send</div>
        <p class="text-grey-7 q-mb-none">
          Sends a test email to the admin address ({{
            testRecipient || '----'
          }}). <strong>Send directly</strong> checks Postmark from the web app.
          <strong>Send via Celery worker</strong> takes the same path as real
          emails: queue, worker, then Postmark.
        </p>
      </q-card-section>

      <q-card-actions class="q-px-md q-pb-md q-gutter-sm">
        <q-btn
          color="primary"
          label="Send directly"
          :loading="directSending"
          :disable="!testRecipient || workerTestRunning"
          @click="sendDirect"
        />
        <q-btn
          color="primary"
          outline
          label="Send via Celery worker"
          :loading="workerTestRunning"
          :disable="!testRecipient || !workerTestAvailable || directSending"
          @click="sendViaWorker"
        />
      </q-card-actions>

      <q-card-section v-if="!statusLoading && !testRecipient" class="q-pt-none">
        <span class="text-negative">
          EMAIL_ADMIN is not set, so there's nowhere to send a test email.
        </span>
      </q-card-section>
      <q-card-section
        v-else-if="!statusLoading && !workerTestAvailable"
        class="q-pt-none text-grey-7"
      >
        The worker test needs a queue. MM_REDIS_HOST is not set, so the web app
        sends emails itself.
      </q-card-section>

      <template v-if="directResult">
        <q-separator />
        <q-card-section>
          <div class="text-subtitle2 q-mb-sm">Direct send</div>
          <div class="row items-center no-wrap">
            <q-icon
              :name="directResult.ok ? icons.success : icons.fail"
              :color="directResult.ok ? 'positive' : 'negative'"
              size="sm"
              class="q-mr-sm"
            />
            <span v-if="directResult.ok">
              Accepted by Postmark (message ID {{ directResult.messageId }})
            </span>
            <span v-else class="text-negative">{{ directResult.error }}</span>
          </div>
        </q-card-section>
      </template>

      <template v-if="workerSteps.length">
        <q-separator />
        <q-card-section>
          <div class="text-subtitle2 q-mb-sm">Send via Celery worker</div>
          <q-list dense>
            <q-item v-for="step in workerSteps" :key="step.label">
              <q-item-section avatar>
                <q-spinner v-if="step.state === 'active'" size="sm" />
                <q-icon
                  v-else
                  :name="stepIcons[step.state].icon"
                  :color="stepIcons[step.state].color"
                  size="sm"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ step.label }}</q-item-label>
                <q-item-label
                  v-if="step.detail"
                  caption
                  :class="{ 'text-negative': step.state === 'failed' }"
                >
                  {{ step.detail }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
      </template>
    </q-card>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import type { AxiosError } from 'axios';
import { api } from 'boot/axios';
import icons from '@icons';

type CheckStatus = 'ok' | 'warning' | 'error' | 'info' | 'unknown';
type StepState = 'done' | 'active' | 'waiting' | 'failed';

interface Check {
  key: string;
  label: string;
  status: CheckStatus;
  value: string;
  detail: string;
}

interface DirectResult {
  ok: boolean;
  messageId?: string;
  error?: string;
}

interface WorkerTest {
  state: 'queued' | 'started' | 'sent' | 'failed';
  failedStep?: 'queue' | 'pickup' | 'send';
  worker?: string;
  messageId?: string;
  error?: string;
}

interface WorkerStep {
  label: string;
  state: StepState;
  detail?: string;
}

const POLL_INTERVAL_MS = 1500;
// Beyond this with nothing picking the task up, assume no worker is running.
const PICKUP_TIMEOUT_MS = 15000;
// Postmark calls time out after 10s, so a picked-up test should finish well
// within this.
const FINISH_TIMEOUT_MS = 45000;

function errorMessage(error: unknown): string {
  const data = (error as AxiosError<{ error?: string; detail?: string }>)
    .response?.data;
  return data?.error || data?.detail || 'The request failed.';
}

export default defineComponent({
  name: 'EmailDelivery',
  data() {
    return {
      checks: [] as Check[],
      testRecipient: null as string | null,
      workerTestAvailable: false,
      statusLoading: true,
      statusError: '',
      directSending: false,
      directResult: null as DirectResult | null,
      workerTest: null as WorkerTest | null,
      pollTimer: undefined as number | undefined,
    };
  },
  computed: {
    icons() {
      return icons;
    },
    statusIcons(): Record<CheckStatus, { icon: string; color: string }> {
      return {
        ok: { icon: icons.success, color: 'positive' },
        warning: { icon: icons.warning, color: 'warning' },
        error: { icon: icons.fail, color: 'negative' },
        info: { icon: icons.info, color: 'grey-7' },
        unknown: { icon: icons.minus, color: 'grey-7' },
      };
    },
    stepIcons(): Record<StepState, { icon: string; color: string }> {
      return {
        done: { icon: icons.success, color: 'positive' },
        active: { icon: icons.minus, color: 'grey-7' },
        waiting: { icon: icons.minus, color: 'grey-5' },
        failed: { icon: icons.fail, color: 'negative' },
      };
    },
    workerTestRunning(): boolean {
      return (
        this.workerTest?.state === 'queued' ||
        this.workerTest?.state === 'started'
      );
    },
    workerSteps(): WorkerStep[] {
      const test = this.workerTest;
      if (!test) return [];

      const failedAt = test.state === 'failed' ? test.failedStep : undefined;
      const reached = { queued: 1, started: 2, sent: 3, failed: 0 }[test.state];
      const stepIndex = { queue: 0, pickup: 1, send: 2 };
      const failedIndex = failedAt ? stepIndex[failedAt] : -1;

      const stateOf = (index: number): StepState => {
        if (failedIndex === index) return 'failed';
        if (failedIndex !== -1) return index < failedIndex ? 'done' : 'waiting';
        if (index < reached) return 'done';
        return index === reached ? 'active' : 'waiting';
      };

      return [
        {
          label: 'Queued',
          state: stateOf(0),
          detail: failedIndex === 0 ? test.error : undefined,
        },
        {
          label: 'Picked up by worker',
          state: stateOf(1),
          detail: failedIndex === 1 ? test.error : test.worker,
        },
        {
          label: 'Accepted by Postmark',
          state: stateOf(2),
          detail:
            failedIndex === 2
              ? test.error
              : test.messageId && `Message ID ${test.messageId}`,
        },
      ];
    },
  },
  mounted() {
    this.loadStatus();
  },
  beforeUnmount() {
    window.clearTimeout(this.pollTimer);
  },
  methods: {
    loadStatus() {
      this.statusLoading = true;
      this.statusError = '';
      api
        .get('/api/admin/email-delivery/status/')
        .then((result) => {
          this.checks = result.data.checks;
          this.testRecipient = result.data.testRecipient;
          this.workerTestAvailable = result.data.workerTestAvailable;
        })
        .catch((error) => {
          this.statusError = `Could not load the delivery status: ${errorMessage(
            error
          )}`;
        })
        .finally(() => {
          this.statusLoading = false;
        });
    },
    sendDirect() {
      this.directSending = true;
      this.directResult = null;
      api
        .post('/api/admin/email-delivery/test/', { via: 'direct' })
        .then((result) => {
          this.directResult = result.data;
        })
        .catch((error) => {
          this.directResult = { ok: false, error: errorMessage(error) };
        })
        .finally(() => {
          this.directSending = false;
        });
    },
    sendViaWorker() {
      window.clearTimeout(this.pollTimer);
      this.workerTest = { state: 'queued' };
      api
        .post('/api/admin/email-delivery/test/', { via: 'worker' })
        .then((result) => {
          this.pollWorkerTest(result.data.taskId, Date.now());
        })
        .catch((error) => {
          this.workerTest = {
            state: 'failed',
            failedStep: 'queue',
            error: errorMessage(error),
          };
        });
    },
    pollWorkerTest(taskId: string, startedAt: number) {
      this.pollTimer = window.setTimeout(() => {
        api
          .get(`/api/admin/email-delivery/test/${taskId}/`)
          .then((result) => {
            const data = result.data;
            const elapsed = Date.now() - startedAt;

            if (data.state === 'SUCCESS' || data.state === 'FAILURE') {
              this.workerTest = data.ok
                ? {
                    state: 'sent',
                    worker: data.worker,
                    messageId: data.messageId,
                  }
                : {
                    state: 'failed',
                    failedStep: 'send',
                    worker: data.worker,
                    error: data.error,
                  };
            } else if (data.state === 'STARTED') {
              this.workerTest = { state: 'started', worker: data.worker };
              if (elapsed > FINISH_TIMEOUT_MS) {
                this.workerTest = {
                  state: 'failed',
                  failedStep: 'send',
                  worker: data.worker,
                  error: `The worker didn't finish within ${
                    FINISH_TIMEOUT_MS / 1000
                  } seconds.`,
                };
              } else {
                this.pollWorkerTest(taskId, startedAt);
              }
            } else if (elapsed > PICKUP_TIMEOUT_MS) {
              this.workerTest = {
                state: 'failed',
                failedStep: 'pickup',
                error: `No worker picked this up within ${
                  PICKUP_TIMEOUT_MS / 1000
                } seconds. Check the Celery workers row above.`,
              };
            } else {
              this.pollWorkerTest(taskId, startedAt);
            }
          })
          .catch((error) => {
            this.workerTest = {
              state: 'failed',
              failedStep: 'pickup',
              error: `Could not check the test's progress: ${errorMessage(
                error
              )}`,
            };
          });
      }, POLL_INTERVAL_MS);
    },
  },
});
</script>

<style lang="scss" scoped>
.check-value {
  white-space: normal;
  overflow-wrap: anywhere;
}

.check-value--side {
  max-width: 45%;
  text-align: right;
}
</style>
