<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-xs">
      <div class="text-h5 col">{{ $t('menuLink.signupProgress') }}</div>
      <q-input
        v-model="search"
        outlined
        dense
        clearable
        debounce="300"
        :placeholder="$t('adminTools.searchMembers')"
      >
        <template v-slot:append>
          <q-icon :name="icons.search" />
        </template>
      </q-input>
    </div>
    <signup-progress-list :search="search || ''" :grid="$q.screen.lt.md" />
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import icons from '@icons';
import SignupProgressList from '@components/AdminTools/SignupProgressList.vue';

export default defineComponent({
  name: 'SignupProgress',
  components: { SignupProgressList },
  data() {
    return {
      search: '' as string | null,
    };
  },
  computed: {
    icons() {
      return icons;
    },
  },
});
</script>
