<template>
  <q-page class="q-pa-md">
    <p class="text-grey-7">
      What members see while signing up, built from this site's current
      settings, membership plans and texts. Nothing here is saved.
    </p>

    <q-banner
      v-if="features.enableRegistration === false"
      rounded
      class="bg-warning text-white q-mb-md"
    >
      <template v-slot:avatar>
        <q-icon :name="icons.warning" />
      </template>
      Registration is closed. Visitors to the registration page see: “{{
        registrationClosedMessage
      }}”
    </q-banner>

    <q-tabs
      v-model="tab"
      align="left"
      no-caps
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="flow" label="Signup flow" />
      <q-tab name="cards" label="Terms cards" />
      <q-tab name="email" label="Welcome email" />
    </q-tabs>
    <q-separator />

    <div v-if="loading" class="q-pa-lg text-center">
      <q-spinner size="3em" />
    </div>

    <q-banner
      v-else-if="loadFailed"
      rounded
      class="bg-negative text-white q-mt-md"
    >
      <template v-slot:avatar>
        <q-icon :name="icons.warning" />
      </template>
      Couldn't load the signup preview. Please try again later.
    </q-banner>

    <q-tab-panels v-else v-model="tab" class="bg-transparent">
      <q-tab-panel name="flow" class="q-px-none">
        <div class="row q-gutter-sm q-mb-md">
          <q-chip
            v-for="section in sections"
            :key="section.id"
            clickable
            outline
            color="primary"
            @click="scrollTo(section.id)"
          >
            {{ section.title }} · {{ section.rows.length }}
          </q-chip>
        </div>

        <section
          v-for="section in sections"
          :key="section.id"
          :id="`signup-section-${section.id}`"
          class="q-mb-lg"
        >
          <div class="text-h6">{{ section.title }}</div>
          <div class="text-caption text-grey-7 q-mb-sm">
            {{ section.where }}
          </div>

          <q-list
            v-if="section.rows.length"
            bordered
            separator
            class="rounded-borders"
          >
            <q-item v-for="(row, i) in section.rows" :key="i" class="q-py-sm">
              <q-item-section>
                <q-item-label class="text-weight-medium">
                  {{ row.label }}
                  <q-badge
                    v-if="row.stepTitle"
                    outline
                    color="primary"
                    class="q-ml-xs"
                  >
                    {{ row.stepTitle }}
                  </q-badge>
                </q-item-label>

                <div class="signup-lines text-body2">
                  <template v-for="(line, j) in row.lines" :key="j">
                    <div v-if="line.kind === 'text'" class="signup-text">
                      “{{ line.text }}”
                    </div>
                    <div
                      v-else-if="line.kind === 'note'"
                      class="text-italic text-grey-7"
                    >
                      {{ line.text }}
                    </div>
                    <ul
                      v-else-if="line.kind === 'items'"
                      class="q-my-xs q-pl-md"
                    >
                      <li v-for="(item, k) in line.items" :key="k">
                        <span class="text-weight-medium">{{ item.title }}</span>
                        <span v-if="item.detail"> — {{ item.detail }}</span>
                      </li>
                    </ul>
                    <div v-else-if="line.kind === 'link'">
                      <a :href="line.href" target="_blank" rel="noopener">{{
                        line.href
                      }}</a>
                    </div>
                    <q-chip
                      v-else-if="line.kind === 'field'"
                      dense
                      square
                      outline
                      icon="mdi-form-textbox"
                      class="q-ml-none"
                    >
                      {{ line.text }}
                    </q-chip>
                    <q-chip
                      v-else-if="line.kind === 'button'"
                      dense
                      outline
                      color="primary"
                      class="q-ml-none"
                      :clickable="!!line.href"
                      @click="line.href && openLink(line.href)"
                    >
                      {{ line.text }}
                      <q-tooltip v-if="line.href">{{ line.href }}</q-tooltip>
                    </q-chip>
                  </template>
                </div>
              </q-item-section>
            </q-item>
          </q-list>

          <div
            v-if="section.skipped.length"
            class="text-caption text-grey-7 q-mt-xs"
          >
            Not shown with the current settings:
            <div v-for="group in section.skipped" :key="group.reason">
              Because {{ group.reason }}: {{ group.labels.join(' · ') }}
            </div>
          </div>
        </section>
      </q-tab-panel>

      <q-tab-panel name="cards" class="q-px-none">
        <p v-if="!termsAcceptanceCards.length" class="text-grey-7">
          No terms &amp; conditions cards are configured.
        </p>
        <div v-else class="row">
          <terms-acceptance-card
            v-for="(card, i) in termsAcceptanceCards"
            :key="i"
            :icon="card.icon"
            :title="card.title"
            :body-html="card.body_html"
            :checkbox-text="card.checkbox_text"
            :model-value="false"
            class="col-12 col-md-6"
          />
        </div>
      </q-tab-panel>

      <q-tab-panel name="email" class="q-px-none">
        <q-card flat bordered>
          <welcome-email-frame
            :html="welcomeEmailHtml"
            title="Welcome email preview"
          />
        </q-card>
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { mapGetters } from 'vuex';
import { api } from 'boot/axios';
import icons from '@icons';
import TermsAcceptanceCard from '@components/Billing/TermsAcceptanceCard.vue';
import WelcomeEmailFrame from '@components/WelcomeEmailFrame.vue';
import {
  signupStates,
  SignupPlan,
  SignupRow,
  SignupSection,
  SignupTier,
  SkippedSignupState,
} from '../../utils/signupStates';

// Admin pages aren't translated: the text here is English. The members' own
// texts in the Signup flow tab come from their translations, through
// signupStates().
const SECTIONS: { id: SignupSection; title: string; where: string }[] = [
  {
    id: 'choose',
    title: 'Choose membership',
    where:
      'The Membership Plan page, for members without a plan. Lapsed members see the same.',
  },
  {
    id: 'finish',
    title: 'Finish signup',
    where: 'The Membership Plan page, once the member has signed up to a plan.',
  },
  {
    id: 'other',
    title: 'Other situations',
    where: 'What the Membership Plan page shows instead of the steps.',
  },
];

// Skipped states grouped by why, so one reason reads once.
function byReason(states: SkippedSignupState[]) {
  const groups = new Map<string, string[]>();
  for (const state of states) {
    groups.set(state.reason, [
      ...(groups.get(state.reason) || []),
      state.label,
    ]);
  }
  return [...groups].map(([reason, labels]) => ({ reason, labels }));
}

export default defineComponent({
  name: 'SignupPreview',
  components: { TermsAcceptanceCard, WelcomeEmailFrame },
  data() {
    return {
      tab: 'flow',
      loading: true,
      loadFailed: false,
      welcomeEmailHtml: '',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      termsAcceptanceCards: [] as any[],
      tiers: [] as SignupTier[],
    };
  },
  computed: {
    ...mapGetters('config', ['features', 'contact', 'siteLocaleCurrency']),
    icons(): typeof icons {
      return icons;
    },
    registrationClosedMessage(): string {
      return (
        this.features.registrationDisabledMessage ||
        this.$t('error.registrationClosed')
      );
    },
    sections(): {
      id: SignupSection;
      title: string;
      where: string;
      rows: SignupRow[];
      skipped: { reason: string; labels: string[] }[];
    }[] {
      const { rows, skipped } = signupStates({
        features: this.features,
        tiers: this.tiers,
        contactEmail: this.contact?.admin || '',
        t: (key, params) => this.$t(key, params || {}),
        price: this.price,
        amount: this.amount,
      });

      return SECTIONS.map((section) => {
        const sectionRows = rows.filter((row) => row.section === section.id);
        const where =
          section.id === 'choose' && sectionRows.length
            ? `${section.where} New members also see “${this.$t('tiers.skipSignup')}” below every step.`
            : section.where;
        return {
          ...section,
          where,
          rows: sectionRows,
          skipped: byReason(
            skipped.filter((state) => state.section === section.id)
          ),
        };
      });
    },
  },
  mounted() {
    Promise.all([
      api.get('/api/admin/signup-preview/'),
      api.get('/api/billing/tiers/'),
    ])
      .then(([preview, tiers]) => {
        this.welcomeEmailHtml = preview.data.welcomeEmailHtml;
        this.termsAcceptanceCards = preview.data.termsAcceptanceCards;
        this.tiers = tiers.data;
      })
      .catch(() => {
        this.loadFailed = true;
      })
      .finally(() => {
        this.loading = false;
      });
  },
  methods: {
    // The prices as the plan cards show them.
    amount(plan: SignupPlan): string {
      return this.$n(plan.cost / 100, 'currency', this.siteLocaleCurrency);
    },
    price(plan: SignupPlan): string {
      return this.$t('paymentPlans.intervalDescription', {
        currency: plan.currency.toUpperCase(),
        amount: this.amount(plan),
        interval: this.$t(
          `paymentPlans.interval.${plan.interval.toLowerCase()}`,
          plan.intervalAmount
        ),
      });
    },
    scrollTo(section: string) {
      document
        .getElementById(`signup-section-${section}`)
        ?.scrollIntoView({ behavior: 'smooth' });
    },
    openLink(href: string) {
      window.open(href, '_blank', 'noopener');
    },
  },
});
</script>

<style scoped>
.signup-lines {
  line-height: 1.5;
}

.signup-text {
  color: var(--q-dark-page, inherit);
}
</style>
