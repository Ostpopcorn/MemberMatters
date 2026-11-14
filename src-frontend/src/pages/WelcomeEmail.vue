<template>
  <q-page class="q-pa-md">
    <p class="text-body1">{{ $t('welcomeEmail.description') }}</p>

    <div v-if="loading" class="q-pa-lg text-center">
      <q-spinner size="3em" />
    </div>

    <q-banner v-else-if="loadFailed" rounded class="bg-negative text-white">
      <template v-slot:avatar>
        <q-icon :name="icons.warning" />
      </template>
      {{ $t('welcomeEmail.loadError') }}
    </q-banner>

    <welcome-email-frame
      v-else
      :html="welcomeEmailHtml"
      :title="$t('menuLink.welcomeEmail')"
    />
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { api } from 'boot/axios';
import icons from '@icons';
import WelcomeEmailFrame from '@components/WelcomeEmailFrame.vue';

export default defineComponent({
  name: 'WelcomeEmailPage',
  components: { WelcomeEmailFrame },
  data() {
    return {
      loading: true,
      loadFailed: false,
      welcomeEmailHtml: '',
    };
  },
  computed: {
    icons() {
      return icons;
    },
  },
  mounted() {
    api
      .get('/api/tools/welcome-email/')
      .then((result) => {
        this.welcomeEmailHtml = result.data.welcomeEmailHtml;
      })
      .catch(() => {
        this.loadFailed = true;
      })
      .finally(() => {
        this.loading = false;
      });
  },
});
</script>
