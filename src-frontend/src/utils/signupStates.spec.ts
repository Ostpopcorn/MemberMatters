import { describe, it, expect } from 'vitest';
import {
  SIGNUP_STATES,
  signupStates,
  SignupStateFeatures,
  SignupTier,
} from './signupStates';
import { postSignupSteps, preSignupSteps } from './signupSteps';

const plan = {
  id: 1,
  name: 'Monthly',
  cost: 40000,
  currency: 'sek',
  interval: 'month',
  intervalAmount: 1,
};
const tiers: SignupTier[] = [
  { id: 1, name: 'Full', plans: [plan] },
  { id: 2, name: 'Student', plans: [] },
];

const everythingOn: SignupStateFeatures = {
  enableMembershipPayments: true,
  enableNewSubscriptions: true,
  enableInvoiceBilling: true,
  signup: {
    termsAcceptanceCards: [{ title: 'House rules' }],
    enableInduction: true,
    requireAccessCard: true,
    memberCanEnterAccessCard: true,
  },
};

const statesFor = (features: SignupStateFeatures, tierList: SignupTier[]) =>
  signupStates({
    features,
    tiers: tierList,
    contactEmail: 'admin@example.org',
    t: (key) => key,
    price: () => 'price',
    amount: () => 'amount',
  });

// Between them, these settings reach every state.
const settings: [SignupStateFeatures, SignupTier[]][] = [
  [everythingOn, tiers],
  [
    {
      ...everythingOn,
      signup: { ...everythingOn.signup, memberCanEnterAccessCard: false },
    },
    [],
  ],
  [{ ...everythingOn, enableNewSubscriptions: false }, tiers],
  [{}, []],
];

describe('signupStates', () => {
  it('shows every state under some settings, and accounts for all of them under each', () => {
    const shown = new Set<string>();

    for (const [features, tierList] of settings) {
      const { rows, skipped } = statesFor(features, tierList);
      rows.forEach((row) => shown.add(row.id));

      const accountedFor = new Set([...rows, ...skipped].map((s) => s.id));
      expect([...accountedFor].sort()).toEqual([...SIGNUP_STATES].sort());
    }

    expect([...shown].sort()).toEqual([...SIGNUP_STATES].sort());
  });

  it('has a row for every step of the real signup', () => {
    const { rows } = statesFor(everythingOn, tiers);
    const stepsIn = (section: string) =>
      new Set(rows.filter((r) => r.section === section).map((r) => r.step));

    const choose = preSignupSteps(everythingOn, {
      tierCount: tiers.length,
      outstanding: ['termsAcceptance'],
    });
    // After paying, billing is only a breadcrumb marked done, not a screen.
    const finish = postSignupSteps(everythingOn).filter((s) => s !== 'billing');

    expect(choose.filter((step) => !stepsIn('choose').has(step))).toEqual([]);
    expect(finish.filter((step) => !stepsIn('finish').has(step))).toEqual([]);
  });
});
