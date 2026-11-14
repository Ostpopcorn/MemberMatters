// Every state a member can be in while signing up, for the admin Signup
// Preview. It doesn't copy the member pages: it lists, per state, the same
// information they show, built from the same sources — the site settings, the
// step lists in signupSteps.ts, the membership types and plans members get,
// and the member pages' own translations.
//
// Every state is accounted for: it is either shown, or skipped with the
// reason it can't happen under the current settings. signupStates.spec.ts
// checks that, and that every step of the real signup has a row.

import {
  postSignupSteps,
  preSignupSteps,
  PostSignupStep,
  PreSignupStep,
} from './signupSteps';

export const SIGNUP_STATES = [
  'choose.terms',
  'choose.tier',
  'choose.noTiers',
  'choose.plan',
  'choose.noPlans',
  'choose.billingInvoice',
  'choose.billingCard',
  'choose.confirmInvoice',
  'choose.confirmCard',
  'choose.signedUpInvoice',
  'choose.signedUpCard',
  'finish.terms',
  'finish.inductionWaiting',
  'finish.inductionDone',
  'finish.accessCardEntry',
  'finish.accessCardCollect',
  'finish.submitted',
  'finish.awaitingPayment',
  'finish.error',
  'other.locked',
  'other.paymentsOff',
  'other.subscriptionsPaused',
  'other.awaitingFirstPayment',
] as const;

export type SignupStateId = (typeof SIGNUP_STATES)[number];

// choose: the membership stepper (SelectTier). finish: the steps after
// paying (SignupRequiredSteps). other: what the Membership Plan page shows
// instead of either.
export type SignupSection = 'choose' | 'finish' | 'other';

export interface SignupPlan {
  id: number | string;
  name: string;
  description?: string;
  cost: number;
  currency: string;
  interval: string;
  intervalAmount: number;
}

export interface SignupTier {
  id: number | string;
  name: string;
  description?: string;
  plans: SignupPlan[];
}

export interface SignupStateFeatures {
  enableMembershipPayments?: boolean;
  enableNewSubscriptions?: boolean;
  enableInvoiceBilling?: boolean;
  invoiceBillingNote?: string;
  signup?: {
    termsAcceptanceCards?: { title?: string; checkbox_text?: string }[];
    enableInduction?: boolean;
    inductionLink?: string;
    requireAccessCard?: boolean;
    memberCanEnterAccessCard?: boolean;
    postInductionUrl?: string;
    enableMembershipApplicationEmail?: boolean;
  };
}

export interface SignupStateSource {
  features: SignupStateFeatures;
  tiers: SignupTier[];
  contactEmail: string;
  // The member pages' translations, and their price formats.
  t: (key: string, params?: Record<string, unknown>) => string;
  price: (plan: SignupPlan) => string;
  amount: (plan: SignupPlan) => string;
}

// What the member sees in a state. `note` is the admin's own explanation;
// everything else is member-facing.
export type SignupLine =
  | { kind: 'text'; text: string }
  | { kind: 'button'; text: string; href?: string }
  | { kind: 'field'; text: string }
  | { kind: 'link'; href: string }
  | { kind: 'items'; items: { title: string; detail?: string }[] }
  | { kind: 'note'; text: string };

export interface SignupRow {
  id: SignupStateId;
  section: SignupSection;
  label: string;
  // The step the member is on, and its title as they see it.
  step?: PreSignupStep | PostSignupStep;
  stepTitle?: string;
  lines: SignupLine[];
}

export interface SkippedSignupState {
  id: SignupStateId;
  section: SignupSection;
  label: string;
  reason: string;
}

// The step titles both steppers show.
const STEP_TITLES: Record<string, Record<string, string>> = {
  choose: {
    terms: 'signup.termsAcceptance',
    tier: 'tiers.select',
    plan: 'paymentPlans.select',
    billing: 'menuLink.billing',
    confirm: 'paymentPlans.confirmSelection',
  },
  finish: {
    terms: 'signup.termsAcceptance',
    induction: 'signup.induction',
    accessCard: 'signup.accessCard',
    confirm: 'confirm',
  },
};

const MEMBER_EMAIL = "‹the member's email›";

export function signupStates(source: SignupStateSource): {
  rows: SignupRow[];
  skipped: SkippedSignupState[];
} {
  const { features, tiers, t } = source;
  const signup = features.signup || {};
  const rows: SignupRow[] = [];
  const skipped: SkippedSignupState[] = [];

  const text = (key: string, params?: Record<string, unknown>): SignupLine => ({
    kind: 'text',
    text: t(key, params),
  });
  const button = (key: string, href?: string): SignupLine => ({
    kind: 'button',
    text: t(key),
    ...(href ? { href } : {}),
  });
  const note = (value: string): SignupLine => ({ kind: 'note', text: value });

  const show = (
    id: SignupStateId,
    label: string,
    step: PreSignupStep | PostSignupStep | undefined,
    lines: SignupLine[]
  ) => {
    const section = id.split('.')[0] as SignupSection;
    const titleKey = step && STEP_TITLES[section]?.[step];
    rows.push({
      id,
      section,
      label,
      ...(step ? { step } : {}),
      ...(titleKey ? { stepTitle: t(titleKey) } : {}),
      lines,
    });
  };
  const skip = (id: SignupStateId, label: string, reason: string) => {
    skipped.push({
      id,
      section: id.split('.')[0] as SignupSection,
      label,
      reason,
    });
  };

  const payments = !!features.enableMembershipPayments;
  const subscriptionsOpen = features.enableNewSubscriptions !== false;
  const invoice = payments && !!features.enableInvoiceBilling;
  const termsCards = signup.termsAcceptanceCards || [];
  const termsLines = [
    text('signup.acceptTerms'),
    {
      kind: 'items',
      items: termsCards.map((card) => ({
        title: card.title || '',
        detail: card.checkbox_text,
      })),
    } as SignupLine,
    button('button.continue'),
  ];

  // An example plan for the steps after picking one: the first one offered.
  const tierWithPlans = tiers.find((tier) => tier.plans.length);
  const examplePlan = tierWithPlans?.plans[0];
  const example: SignupLine[] =
    tierWithPlans && examplePlan
      ? [note(`Example: ${tierWithPlans.name} · ${examplePlan.name}`)]
      : [];

  // Choose membership.
  const chooseOff = !payments
    ? 'membership payments are off'
    : !subscriptionsOpen
      ? 'new subscriptions are paused'
      : null;
  const chooseStates: [SignupStateId, string][] = [
    ['choose.terms', 'Terms'],
    ['choose.tier', 'Membership type'],
    ['choose.noTiers', 'No membership types'],
    ['choose.plan', 'Payment plan'],
    ['choose.noPlans', 'Payment plan with no plans'],
    ['choose.billingInvoice', 'Billing: invoice'],
    ['choose.billingCard', 'Billing: card'],
    ['choose.confirmInvoice', 'Confirm: invoice'],
    ['choose.confirmCard', 'Confirm: card'],
    ['choose.signedUpInvoice', 'Signed up: invoice'],
    ['choose.signedUpCard', 'Signed up: card'],
  ];

  if (chooseOff) {
    for (const [id, label] of chooseStates) skip(id, label, chooseOff);
  } else {
    // A new member hasn't accepted the terms yet.
    const preSteps = preSignupSteps(features, {
      tierCount: tiers.length,
      outstanding: ['termsAcceptance'],
    });

    if (preSteps.includes('terms')) {
      show('choose.terms', 'Terms', 'terms', termsLines);
    } else {
      skip('choose.terms', 'Terms', 'no terms cards are set up');
    }

    if (tiers.length === 0) {
      show('choose.noTiers', 'No membership types', 'tier', [
        text('tiers.noTiers'),
      ]);
      skip('choose.tier', 'Membership type', 'no membership types are set up');
    } else {
      skip(
        'choose.noTiers',
        'No membership types',
        'membership types are set up'
      );
      if (preSteps.includes('tier')) {
        show('choose.tier', 'Membership type', 'tier', [
          text('tiers.selectToContinue'),
          {
            kind: 'items',
            items: tiers.map((tier) => ({
              title: tier.name,
              detail: [
                tier.plans.length
                  ? t('tiers.plansFrom', {
                      plan: source.price(cheapest(tier.plans)),
                    })
                  : '',
                tier.description || '',
              ]
                .filter(Boolean)
                .join(' — '),
            })),
          },
          button('button.select'),
        ]);
      } else {
        skip(
          'choose.tier',
          'Membership type',
          'there is only one membership type, so it is preselected'
        );
      }
    }

    const withPlans = tiers.filter((tier) => tier.plans.length);
    const withoutPlans = tiers.filter((tier) => !tier.plans.length);
    for (const tier of withPlans) {
      show('choose.plan', `Payment plan: ${tier.name}`, 'plan', [
        text('paymentPlans.selectToContinue'),
        {
          kind: 'items',
          items: tier.plans.map((plan) => ({
            title: plan.name,
            detail: [source.price(plan), plan.description || '']
              .filter(Boolean)
              .join(' — '),
          })),
        },
        button('button.select'),
      ]);
    }
    if (!withPlans.length) {
      skip('choose.plan', 'Payment plan', 'no payment plans are set up');
    }
    for (const tier of withoutPlans) {
      show('choose.noPlans', `Payment plan: ${tier.name}`, 'plan', [
        text('paymentPlans.noPlans'),
      ]);
    }
    if (!withoutPlans.length) {
      skip(
        'choose.noPlans',
        'Payment plan with no plans',
        tiers.length
          ? 'every membership type has plans'
          : 'no membership types are set up'
      );
    }

    if (!examplePlan) {
      for (const [id, label] of chooseStates.slice(5)) {
        skip(id, label, 'no payment plans are set up');
      }
    } else {
      const methodPicker = (method: 'invoice' | 'card'): SignupLine[] =>
        invoice
          ? [
              text('billing.selectMethod'),
              text(
                method === 'invoice'
                  ? 'billing.payByInvoice'
                  : 'billing.payByCard'
              ),
              text(
                method === 'invoice'
                  ? 'billing.invoiceDescription'
                  : 'billing.cardDescription'
              ),
            ]
          : [];
      const confirmLines = (method: 'invoice' | 'card'): SignupLine[] => [
        ...example,
        text(
          method === 'invoice'
            ? 'billing.invoiceAmount'
            : 'paymentPlans.dueToday',
          { amount: source.amount(examplePlan) }
        ),
        text('tiers.confirm', {
          intervalDescription: source.price(examplePlan),
        }),
        text('tiers.confirmDelay'),
        button('button.back'),
        button(method === 'invoice' ? 'tiers.finishInvoice' : 'tiers.finish'),
      ];

      if (invoice) {
        show('choose.billingInvoice', 'Billing: invoice', 'billing', [
          text('memberbucks.selectToContinue'),
          ...methodPicker('invoice'),
          ...(features.invoiceBillingNote
            ? [
                {
                  kind: 'text',
                  text: features.invoiceBillingNote,
                } as SignupLine,
              ]
            : []),
          button('button.back'),
          button('button.continue'),
        ]);
      } else {
        skip(
          'choose.billingInvoice',
          'Billing: invoice',
          'invoice billing is off'
        );
      }
      show('choose.billingCard', 'Billing: card', 'billing', [
        text('memberbucks.selectToContinue'),
        ...methodPicker('card'),
        note('The card details form (Stripe), or the saved card'),
        button('button.back'),
        button('button.continue'),
      ]);

      if (invoice) {
        show(
          'choose.confirmInvoice',
          'Confirm: invoice',
          'confirm',
          confirmLines('invoice')
        );
      } else {
        skip(
          'choose.confirmInvoice',
          'Confirm: invoice',
          'invoice billing is off'
        );
      }
      show(
        'choose.confirmCard',
        'Confirm: card',
        'confirm',
        confirmLines('card')
      );

      if (invoice) {
        show('choose.signedUpInvoice', 'Signed up: invoice', 'confirm', [
          text('paymentPlans.signupSuccess'),
          text('paymentPlans.signupSuccessInvoiceDescription'),
        ]);
      } else {
        skip(
          'choose.signedUpInvoice',
          'Signed up: invoice',
          'invoice billing is off'
        );
      }
      show('choose.signedUpCard', 'Signed up: card', 'confirm', [
        text('paymentPlans.signupSuccess'),
        text('paymentPlans.signupSuccessDescription'),
      ]);
    }
  }

  // Finish signup.
  const postSteps = postSignupSteps(features);

  if (postSteps.includes('terms')) {
    show('finish.terms', 'Terms', 'terms', [
      note("Only if the member didn't accept them before paying"),
      ...termsLines,
    ]);
  } else {
    skip('finish.terms', 'Terms', 'no terms cards are set up');
  }

  if (postSteps.includes('induction')) {
    const link = signup.inductionLink || '';
    const canvas = link.includes('canvas.instructure.com');
    const intro = [
      text('signup.completeInduction'),
      text('signup.completeInductionDescription'),
      ...(canvas
        ? [text('signup.canvasEmailWarning', { email: MEMBER_EMAIL })]
        : []),
    ];
    show('finish.inductionWaiting', 'Induction: waiting', 'induction', [
      ...intro,
      canvas
        ? ({ kind: 'link', href: link } as SignupLine)
        : button('signup.startInduction', link),
      text('signup.waitingCompletion'),
      text('progress', { percent: 0 }),
      note('Continue stays disabled until the induction is done'),
      button('button.continue'),
    ]);
    show('finish.inductionDone', 'Induction: done', 'induction', [
      ...intro,
      text('signup.completedInduction'),
      button('button.continue'),
    ]);
  } else {
    skip('finish.inductionWaiting', 'Induction: waiting', 'induction is off');
    skip('finish.inductionDone', 'Induction: done', 'induction is off');
  }

  if (postSteps.includes('accessCard') && signup.memberCanEnterAccessCard) {
    show(
      'finish.accessCardEntry',
      'Access card: member enters it',
      'accessCard',
      [
        text('signup.assignAccessCard'),
        text('signup.assignAccessCardDescription'),
        text('signup.assignAccessCardWarning', { email: MEMBER_EMAIL }),
        { kind: 'field', text: t('signup.accessCardNumber') },
        button('button.continue'),
      ]
    );
  } else {
    skip(
      'finish.accessCardEntry',
      'Access card: member enters it',
      postSteps.includes('accessCard')
        ? "members can't enter their own card"
        : 'no access card is required'
    );
  }
  if (postSteps.includes('accessCard') && !signup.memberCanEnterAccessCard) {
    show(
      'finish.accessCardCollect',
      'Access card: collect from staff',
      'accessCard',
      [
        text('signup.assignAccessCard'),
        text('signup.collectAccessCardDescription'),
        button('button.contactUs', signup.postInductionUrl),
      ]
    );
  } else {
    skip(
      'finish.accessCardCollect',
      'Access card: collect from staff',
      postSteps.includes('accessCard')
        ? 'members enter their own card'
        : 'no access card is required'
    );
  }

  const applicationEmail = !!signup.enableMembershipApplicationEmail;
  show('finish.submitted', 'Submitted', 'confirm', [
    text(applicationEmail ? 'signup.submitted' : 'signup.submittedNoEmail'),
    text(
      applicationEmail
        ? 'signup.submittedDescription'
        : 'signup.submittedDescriptionNoEmail'
    ),
    button('signup.continueToDashboard'),
  ]);
  if (invoice) {
    show('finish.awaitingPayment', 'Awaiting invoice payment', 'confirm', [
      text('signup.awaitingPaymentTitle'),
      text('signup.awaitingInvoicePayment'),
      button('signup.continueToDashboard'),
    ]);
  } else {
    skip(
      'finish.awaitingPayment',
      'Awaiting invoice payment',
      'invoice billing is off'
    );
  }
  show('finish.error', 'Error', 'confirm', [
    text('signup.error'),
    text('signup.errorDescription', { email: source.contactEmail }),
    text('signup.errorMessageDescription'),
    note('Followed by the error message from the server'),
  ]);

  // Other situations, on the Membership Plan page.
  show('other.locked', 'Account locked', undefined, [
    note('An admin has locked the account'),
    text('paymentPlans.lockedTitle'),
    text('paymentPlans.lockedMessage'),
  ]);
  if (!payments) {
    show('other.paymentsOff', 'Payments switched off', undefined, [
      text('billing.membershipPaymentsDisabled'),
    ]);
  } else {
    skip(
      'other.paymentsOff',
      'Payments switched off',
      'membership payments are on'
    );
  }
  if (payments && !subscriptionsOpen) {
    show('other.subscriptionsPaused', 'New subscriptions paused', undefined, [
      text('billing.newSubscriptionsDisabled'),
    ]);
  } else {
    skip(
      'other.subscriptionsPaused',
      'New subscriptions paused',
      payments ? 'new subscriptions are open' : 'membership payments are off'
    );
  }
  if (invoice) {
    show(
      'other.awaitingFirstPayment',
      'Waiting for first invoice payment',
      undefined,
      [
        text('membershipStatusCard.stateBanner.noob'),
        ...example,
        text('billing.awaitingInvoicePayment'),
        button('billing.viewInvoice'),
      ]
    );
  } else {
    skip(
      'other.awaitingFirstPayment',
      'Waiting for first invoice payment',
      'invoice billing is off'
    );
  }

  return { rows, skipped };
}

function cheapest(plans: SignupPlan[]): SignupPlan {
  return plans.reduce((prev, curr) => (prev.cost < curr.cost ? prev : curr));
}
