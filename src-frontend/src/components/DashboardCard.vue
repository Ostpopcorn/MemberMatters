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
            <q-btn v-if="link.route" :to="link.to" flat>
              {{ link.label }}
            </q-btn>
            <q-btn v-else :href="link.url" target="_blank" flat>
              {{ link.label }}
            </q-btn>
          </template>
        </q-card-actions>
      </div>
    </q-card>
  </div>
</template>

<script>
import DOMPurify from 'dompurify';
import { mapGetters } from 'vuex';
import PageAndRouteConfig from '../pages/pageAndRouteConfig';
import { ALLOWED_ATTR, ALLOWED_TAGS } from '../utils/cardHtml';
import { cardLinks, portalPages } from '../utils/portalPages';

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
    ...mapGetters('config', ['features']),
    ...mapGetters('profile', ['profile']),
    visibleLinks() {
      return cardLinks(
        this.links,
        portalPages(PageAndRouteConfig, this.features),
        this.profile
      );
    },
    sanitizedDescription() {
      return DOMPurify.sanitize(this.description, {
        ALLOWED_TAGS,
        ALLOWED_ATTR,
      });
    },
  },
};
</script>
