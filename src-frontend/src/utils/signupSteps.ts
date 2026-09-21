// Shared source of truth for signup steps.
//
// `enabledSignupSteps` is the canonical list of member-facing *requirements*,
// keyed to the backend's `requiredSteps` strings via REQUIRED_STEP_KEY. It
// drives the read-only views (MembershipStatusCard, admin Signup Progress).
//
// The two signup steppers render flows rather than bare requirements, so they
// build their lists from `preSignupSteps` / `postSignupSteps` below, which
// expand the canonical list with the UI-only steps each one needs. Everything
// derives from the same predicates, so the three can't drift.

export type SignupStep = 'payment' | 'terms' | 'induction' | 'accessCard';

// The pre-payment stepper (SelectTier) expands 'payment' into its own steps.
export type PreSignupStep = 'terms' | 'tier' | 'plan' | 'billing' | 'confirm';

export interface SignupStepState {
  complete: boolean;
  pending: boolean;
}

interface SignupFeatures {
  enableMembershipPayments?: boolean;
  signup?: {
    termsAcceptanceCards?: unknown[];
    enableInduction?: boolean;
    requireAccessCard?: boolean;
  };
}

const termsConfigured = (features: SignupFeatures) =>
  (features.signup?.termsAcceptanceCards || []).length > 0;
const inductionEnabled = (features: SignupFeatures) =>
  !!features.signup?.enableInduction;
const accessCardRequired = (features: SignupFeatures) =>
  !!features.signup?.requireAccessCard;

// Order here = display order.
export function enabledSignupSteps(features: SignupFeatures): SignupStep[] {
  const steps: SignupStep[] = [];
  if (features.enableMembershipPayments) steps.push('payment');
  if (termsConfigured(features)) steps.push('terms');
  if (inductionEnabled(features)) steps.push('induction');
  if (accessCardRequired(features)) steps.push('accessCard');
  return steps;
}

// Order here = visual order in the pre-payment stepper. Adding a step is one
// line. Build this ONCE, after its inputs have loaded, and hold the result in
// a data field: q-stepper's v-model is an index into this list, so a list that
// reshapes underneath it silently re-points at a different panel.
export function preSignupSteps(
  features: SignupFeatures,
  { tierCount }: { tierCount: number }
): PreSignupStep[] {
  const steps: PreSignupStep[] = [];
  // Exactly one tier — it gets preselected, so drop the picker. Note `!== 1`
  // rather than `> 1`: with zero tiers the step has to stay, because it is
  // what renders the "no tiers available" empty state.
  if (tierCount !== 1) steps.push('tier');
  steps.push('plan');
  steps.push('billing');
  steps.push('confirm');
  return steps;
}

export function stepIndex<T extends string>(steps: T[], name: T): number {
  return steps.indexOf(name);
}

// The next step after `from` that this member actually needs to stop on.
// Returns null when `from` is last. `skip` steps over anything already
// satisfied (e.g. an access card carried over from a previous membership).
export function nextStepAfter<T extends string>(
  steps: T[],
  from: T,
  skip: (step: T) => boolean = () => false
): T | null {
  for (let i = steps.indexOf(from) + 1; i < steps.length; i++) {
    if (!skip(steps[i])) return steps[i];
  }
  return null;
}

// Maps a checklist step to the key the backend reports in `requiredSteps`.
const REQUIRED_STEP_KEY: Record<Exclude<SignupStep, 'payment'>, string> = {
  terms: 'termsAcceptance',
  induction: 'induction',
  accessCard: 'accessCard',
};

export function signupStepStatus(
  step: SignupStep,
  requiredSteps: string[] | null,
  subscriptionState: string | null | undefined
): SignupStepState {
  if (step === 'payment') {
    return {
      complete: subscriptionState === 'active',
      pending: subscriptionState === 'pending',
    };
  }
  const key = REQUIRED_STEP_KEY[step];
  return {
    // requiredSteps === null means "not loaded yet" — treat as incomplete.
    complete: requiredSteps !== null && !requiredSteps.includes(key),
    pending: false,
  };
}

// The one step the member should do next: first that's neither complete nor
// merely pending. null when nothing is actionable (all done or only pending).
export function nextSignupStep(
  features: SignupFeatures,
  requiredSteps: string[] | null,
  subscriptionState: string | null | undefined
): SignupStep | null {
  const next = enabledSignupSteps(features).find((step) => {
    const status = signupStepStatus(step, requiredSteps, subscriptionState);
    return !status.complete && !status.pending;
  });
  return next || null;
}
