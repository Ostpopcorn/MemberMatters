<template>
  <q-card
    flat
    bordered
    class="member-summary-card cursor-pointer full-height"
    tabindex="0"
    @click="$emit('click')"
    @keydown.enter="$emit('click')"
  >
    <q-card-section class="q-pb-sm">
      <div class="row items-center no-wrap">
        <div class="col ellipsis text-subtitle1 text-weight-medium">
          {{ member.name?.full || $t('error.noValue') }}
          <span
            v-if="member.screenName"
            class="text-body2 text-weight-regular text-grey-7"
          >
            ({{ member.screenName }})
          </span>
        </div>
        <q-icon
          v-if="member.stateLocked"
          :name="icons.lock"
          color="warning"
          size="sm"
          class="q-ml-xs"
        >
          <q-tooltip>{{ $t('adminTools.stateLockedTooltip') }}</q-tooltip>
        </q-icon>
        <q-icon
          v-if="member.adminDisabledAccess"
          :name="icons.accessDisabled"
          color="negative"
          size="sm"
          class="q-ml-xs"
        >
          <q-tooltip>{{ $t('adminTools.accessDisabledTooltip') }}</q-tooltip>
        </q-icon>
      </div>
      <div class="text-caption text-grey-7 ellipsis">{{ member.email }}</div>

      <!-- Headed like the table columns, so the two badges can't be mixed up. -->
      <div class="row q-col-gutter-md q-mt-none">
        <div class="col-auto">
          <div class="text-caption text-grey-7">
            {{ $t('tableHeading.status') }}
          </div>
          <q-badge :color="memberStateColor(member.state)">
            {{ $t(`adminTools.memberStatusString.${member.state}`) }}
          </q-badge>
        </div>
        <div class="col-auto">
          <div class="text-caption text-grey-7">
            {{ $t('tableHeading.subscriptionStatus') }}
          </div>
          <q-badge
            outline
            :color="subscriptionStatusColor(member.subscriptionStatus)"
          >
            {{
              $t(
                `adminTools.subscriptionStatusString.${member.subscriptionStatus}`
              )
            }}
          </q-badge>
        </div>
      </div>
    </q-card-section>

    <q-card-section v-if="$slots.default" class="q-pt-none">
      <slot />
    </q-card-section>
  </q-card>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue';
import icons from '@icons';
import { MemberProfile } from 'types/member';
import {
  memberStateColor,
  subscriptionStatusColor,
} from '../../utils/memberStatus';

// One member in the card view of the admin member lists. The default slot
// holds whatever the list wants to add under the name and status badges.
export default defineComponent({
  name: 'MemberSummaryCard',
  props: {
    member: {
      type: Object as PropType<MemberProfile>,
      required: true,
    },
  },
  emits: ['click'],
  computed: {
    icons() {
      return icons;
    },
  },
  methods: {
    memberStateColor,
    subscriptionStatusColor,
  },
});
</script>

<style scoped lang="scss">
.member-summary-card {
  transition: box-shadow 0.2s;

  &:hover,
  &:focus-visible {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  }
}
</style>
