<template>
  <div class="q-pa-md flex col">
    <q-card class="flex col items-stretch content-between justify-left">
      <div class="grow-1">
        <q-item>
          <q-item-section avatar>
            <q-avatar>
              <q-icon :name="icon" />
            </q-avatar>
          </q-item-section>

          <q-item-section>
            <q-item-label>{{ title }}</q-item-label>
          </q-item-section>
        </q-item>

        <q-separator />

        <q-card-section>
          <div v-html="sanitizedDescription" />
        </q-card-section>
      </div>

      <div class="full-width">
        <q-separator dark />

        <q-card-actions>
          <template v-for="(link, index) in visibleLinks" :key="index">
            <q-btn v-if="link.route" :to="{ name: link.route }" flat>
              {{ link.label }}
            </q-btn>
            <q-btn v-else :href="link.url" target="_blank" flat>
              {{ Platform.is.electron ? link.url : link.label }}
            </q-btn>
          </template>
        </q-card-actions>
      </div>
    </q-card>
  </div>
</template>

<script>
import { Platform } from 'quasar';
import DOMPurify from 'dompurify';

export default {
  name: 'DashboardCard',
  props: {
    title: {
      type: String,
      required: true,
    },
    icon: {
      type: String,
      required: true,
    },
    description: {
      type: String,
      required: true,
    },
    // [{ label, url }] for a website or [{ label, route }] for a portal page.
    links: {
      type: Array,
      required: false,
      default: () => [],
    },
  },
  computed: {
    Platform() {
      return Platform;
    },
    visibleLinks() {
      // A link to a page that no longer exists would throw when resolved.
      return this.links.filter(
        (link) => !link.route || this.$router.hasRoute(link.route)
      );
    },
    sanitizedDescription() {
      // Allow links (with target/rel) so cards can link out; everything
      // else falls back to DOMPurify's safe defaults. Matches the policy
      // used by the terms-acceptance and welcome-email cards.
      return DOMPurify.sanitize(this.description, {
        ADD_ATTR: ['target', 'rel'],
      });
    },
  },
};
</script>
