<template>
  <q-dialog
    :model-value="modelValue"
    persistent
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <q-card style="width: 1100px; max-width: 95vw">
      <q-card-section>
        <div class="text-h6">
          {{ card ? 'Edit Card' : 'Add Card' }}
        </div>
      </q-card-section>

      <q-form @submit="save">
        <q-card-section class="row q-col-gutter-lg q-pt-none">
          <div class="col-12 col-md-7">
            <q-input
              v-model="form.title"
              outlined
              maxlength="255"
              label="Title"
              :rules="[required]"
            />

            <q-input
              v-model="form.icon"
              outlined
              maxlength="100"
              label="Icon"
              hint="A Material Design Icons name, e.g. mdi-calendar"
              :rules="[required]"
            >
              <template #append>
                <q-icon :name="form.icon || icons.info" />
              </template>
            </q-input>

            <div class="text-caption text-grey-7 q-mt-md q-mb-xs">
              Description
            </div>
            <q-editor
              v-model="form.description"
              min-height="8rem"
              :toolbar="[
                ['bold', 'italic'],
                ['unordered', 'ordered'],
                ['link'],
              ]"
            />

            <div class="text-subtitle2 q-mt-lg q-mb-sm">Buttons</div>
            <div
              v-for="(link, index) in form.links"
              :key="link.key"
              class="row q-col-gutter-sm items-start"
            >
              <q-input
                v-model="link.label"
                class="col-12 col-sm-3"
                outlined
                dense
                label="Button text"
                :rules="[required]"
              />
              <q-select
                v-model="link.type"
                class="col-12 col-sm-3"
                outlined
                dense
                emit-value
                map-options
                :options="linkTypeOptions"
              />
              <q-input
                v-if="link.type === 'url'"
                v-model="link.url"
                class="col"
                outlined
                dense
                placeholder="https://"
                label="URL"
                :rules="[required, validUrl]"
              />
              <q-select
                v-else
                v-model="link.route"
                class="col"
                outlined
                dense
                emit-value
                map-options
                label="Page"
                :options="pageOptions"
                :rules="[required]"
              />
              <div class="col-auto">
                <q-btn
                  flat
                  round
                  dense
                  :icon="icons.delete"
                  aria-label="Remove button"
                  @click="form.links.splice(index, 1)"
                />
              </div>
            </div>
            <q-btn
              flat
              color="primary"
              :icon="icons.addAlternative"
              label="Add Button"
              @click="addLink"
            />
          </div>

          <div class="col-12 col-md-5">
            <div class="text-caption text-grey-7">Preview</div>
            <!-- Previews only: its buttons would navigate away mid-edit. -->
            <div class="preview">
              <dashboard-card
                :title="form.title"
                :icon="form.icon"
                :description="form.description"
                :links="previewLinks"
              />
            </div>
          </div>
        </q-card-section>

        <q-card-section v-if="error" class="q-pt-none">
          <q-banner class="bg-negative text-white">{{ error }}</q-banner>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Cancel" :disable="saving" />
          <q-btn color="primary" type="submit" label="Save" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script>
import icons from '@icons';
import DashboardCard from '@components/DashboardCard.vue';
import PageAndRouteConfig from '../../pages/pageAndRouteConfig';
import { portalPages } from '../../utils/portalPages';
import enAU from '../../i18n/en-AU';

const linkTypeOptions = [
  { label: 'Website', value: 'url' },
  { label: 'Portal page', value: 'route' },
];

let nextLinkKey = 0;

function formLink(link = {}) {
  return {
    key: nextLinkKey++,
    label: link.label ?? '',
    type: link.route ? 'route' : 'url',
    url: link.url ?? '',
    route: link.route ?? null,
  };
}

export default {
  name: 'DashboardCardDialog',
  components: { DashboardCard },
  props: {
    modelValue: {
      type: Boolean,
      required: true,
    },
    // The card being edited, or null to add a new one.
    card: {
      type: Object,
      default: null,
    },
  },
  emits: ['update:modelValue', 'saved'],
  data() {
    return {
      form: { title: '', icon: '', description: '', links: [] },
      saving: false,
      error: '',
    };
  },
  computed: {
    icons() {
      return icons;
    },
    linkTypeOptions() {
      return linkTypeOptions;
    },
    pageOptions() {
      return portalPages(PageAndRouteConfig).map((page) => ({
        label: enAU.menuLink[page.name] ?? page.name,
        value: page.name,
      }));
    },
    apiLinks() {
      return this.form.links.map((link) =>
        link.type === 'route'
          ? { label: link.label, route: link.route }
          : { label: link.label, url: link.url }
      );
    },
    previewLinks() {
      return this.apiLinks.filter(
        (link) => link.label && (link.url || link.route)
      );
    },
  },
  watch: {
    modelValue(open) {
      if (open) this.reset();
    },
  },
  methods: {
    required(value) {
      return (
        (typeof value === 'string' ? value.trim() !== '' : !!value) ||
        'Required'
      );
    },
    validUrl(value) {
      // Mirrors the API's check.
      return (
        /^\s*((https?|mailto):|\/)/i.test(value) ||
        'Must start with http://, https://, mailto: or /'
      );
    },
    reset() {
      this.form = {
        title: this.card?.title ?? '',
        icon: this.card?.icon ?? '',
        description: this.card?.description ?? '',
        links: (this.card?.links ?? []).map(formLink),
      };
      this.error = '';
    },
    addLink() {
      this.form.links.push(formLink());
    },
    save() {
      const payload = {
        title: this.form.title,
        icon: this.form.icon,
        description: this.form.description,
        links: this.apiLinks,
      };
      const request = this.card
        ? this.$axios.put(
            `/api/admin/dashboard-cards/${this.card.id}/`,
            payload
          )
        : this.$axios.post('/api/admin/dashboard-cards/', payload);

      this.saving = true;
      this.error = '';
      request
        .then(() => {
          this.$emit('saved');
          this.$emit('update:modelValue', false);
        })
        .catch((e) => {
          const errors = e.response?.status === 400 ? e.response.data : null;
          this.error = errors
            ? Object.values(errors).flat().join(' ')
            : 'Failed to save the card.';
        })
        .finally(() => {
          this.saving = false;
        });
    },
  },
};
</script>

<style lang="sass" scoped>
.preview
  pointer-events: none
</style>
