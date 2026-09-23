<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">Dashboard Cards</div>
    <p class="text-grey-7">
      The Member Resources cards shown on every member's dashboard. The welcome
      email uses these cards too, unless the WELCOME_EMAIL_CARDS setting is
      filled in.
    </p>

    <q-btn
      class="q-mb-md"
      color="primary"
      :icon="icons.addAlternative"
      label="Add Card"
      @click="openDialog(null)"
    />

    <div v-if="loading" class="q-pa-lg text-center">
      <q-spinner size="3em" />
    </div>

    <p v-else-if="!cards.length" class="text-grey-7">There are no cards yet.</p>

    <q-list v-else bordered separator>
      <q-item v-for="(card, index) in cards" :key="card.id">
        <q-item-section avatar>
          <q-icon
            :name="card.icon"
            :color="card.enabled ? 'primary' : 'grey'"
            size="md"
          />
        </q-item-section>

        <q-item-section>
          <q-item-label :class="{ 'text-grey': !card.enabled }">
            {{ card.title }}
          </q-item-label>
          <q-item-label caption>
            {{ card.links.map((link) => link.label).join(', ') }}
          </q-item-label>
        </q-item-section>

        <q-item-section side>
          <div class="row items-center no-wrap">
            <q-toggle
              :model-value="card.enabled"
              :disable="busy"
              @update:model-value="setEnabled(card, $event)"
            >
              <q-tooltip :delay="500"> Shown on the dashboard </q-tooltip>
            </q-toggle>
            <q-btn
              flat
              round
              dense
              :icon="icons.moveUp"
              aria-label="Move up"
              :disable="busy || index === 0"
              @click="move(index, -1)"
            />
            <q-btn
              flat
              round
              dense
              :icon="icons.moveDown"
              aria-label="Move down"
              :disable="busy || index === cards.length - 1"
              @click="move(index, 1)"
            />
            <q-btn
              flat
              round
              dense
              :icon="icons.edit"
              aria-label="Edit card"
              @click="openDialog(card)"
            />
            <q-btn
              flat
              round
              dense
              color="negative"
              :icon="icons.delete"
              aria-label="Delete card"
              :disable="busy"
              @click="confirmDelete(card)"
            />
          </div>
        </q-item-section>
      </q-item>
    </q-list>

    <dashboard-card-dialog
      v-model="dialogOpen"
      :card="editingCard"
      @saved="refresh"
    />
  </q-page>
</template>

<script>
import icons from '@icons';
import { mapActions } from 'vuex';
import DashboardCardDialog from '@components/AdminTools/DashboardCardDialog.vue';

export default {
  name: 'ManageDashboard',
  components: { DashboardCardDialog },
  data() {
    return {
      cards: [],
      loading: false,
      busy: false,
      dialogOpen: false,
      editingCard: null,
    };
  },
  computed: {
    icons() {
      return icons;
    },
  },
  mounted() {
    this.loading = true;
    this.fetchCards().finally(() => {
      this.loading = false;
    });
  },
  methods: {
    ...mapActions('config', ['getSiteConfig']),
    fetchCards() {
      return this.$axios
        .get('/api/admin/dashboard-cards/')
        .then((response) => {
          this.cards = response.data;
        })
        .catch(() => this.notifyError('Failed to load the dashboard cards.'));
    },
    // Reloads the list and the site config, so the dashboard shows the change
    // without a page reload.
    refresh() {
      return Promise.allSettled([this.fetchCards(), this.getSiteConfig()]);
    },
    notifyError(message) {
      this.$q.notify({ type: 'negative', message });
    },
    update(request, errorMessage) {
      this.busy = true;
      return request
        .catch(() => this.notifyError(errorMessage))
        .then(this.refresh)
        .finally(() => {
          this.busy = false;
        });
    },
    openDialog(card) {
      this.editingCard = card;
      this.dialogOpen = true;
    },
    setEnabled(card, enabled) {
      this.update(
        this.$axios.put(`/api/admin/dashboard-cards/${card.id}/`, { enabled }),
        'Failed to save the card.'
      );
    },
    move(index, offset) {
      const ids = this.cards.map((card) => card.id);
      [ids[index], ids[index + offset]] = [ids[index + offset], ids[index]];
      this.update(
        this.$axios.put('/api/admin/dashboard-cards/order/', { ids }),
        'Failed to reorder the cards. The list has been reloaded, please try again.'
      );
    },
    confirmDelete(card) {
      this.$q
        .dialog({
          title: 'Delete Card',
          message: `Delete the card "${card.title}"? This cannot be undone.`,
          ok: { label: 'Delete', color: 'negative', flat: true },
          cancel: { label: 'Cancel', flat: true },
          persistent: true,
        })
        .onOk(() => {
          this.update(
            this.$axios.delete(`/api/admin/dashboard-cards/${card.id}/`),
            'Failed to delete the card.'
          );
        });
    },
  },
};
</script>
