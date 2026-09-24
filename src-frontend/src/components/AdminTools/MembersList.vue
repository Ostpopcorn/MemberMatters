<template>
  <div style="max-width: 100%">
    <q-table
      :rows="displayMemberList"
      :no-data-label="$t('adminTools.noMembers')"
      :columns="columns"
      row-key="email"
      :filter="filter"
      :filter-method="fuzzyFilter"
      v-model:pagination="pagination"
      :loading="loading"
      :grid="$q.screen.lt.md"
      class="full-width"
      @row-click="
        (evt, row) => {
          $router.push({
            name: 'manageMember',
            params: { memberId: row.id },
          });
        }
      "
    >
      <template v-slot:top-left>
        <div class="row flex items-start">
          <member-export-buttons
            :class="{ 'full-width': $q.screen.lt.md }"
            :members="displayMemberList"
            :csv-columns="csvColumns"
          />
          <div v-if="$q.screen.lt.md" class="full-width">
            <q-select
              v-model="memberState"
              class="q-mb-sm"
              outlined
              emit-value
              map-options
              :options="filterOptions"
              :label="$t('adminTools.filterOptions')"
              dense
            />
          </div>
        </div>
      </template>
      <template v-slot:top-right>
        <q-select
          v-if="$q.screen.gt.sm"
          v-model="memberState"
          class="q-mr-sm"
          style="min-width: 100px"
          outlined
          emit-value
          map-options
          :options="filterOptions"
          :label="$t('adminTools.filterOptions')"
          dense
        />

        <q-input
          ref="searchInput"
          v-model="filter"
          outlined
          dense
          clearable
          :clear-icon="icons.close"
          debounce="300"
          :placeholder="$t('adminTools.searchMembers')"
        >
          <template v-slot:append>
            <q-icon :name="icons.search" />
          </template>
        </q-input>
      </template>

      <template v-slot:body-cell-status="props">
        <q-td :props="props">
          {{ props.value }}
          <q-icon
            v-if="props.row.stateLocked"
            :name="icons.lock"
            color="warning"
            size="sm"
            class="q-ml-xs"
          >
            <q-tooltip>{{ $t('adminTools.stateLockedTooltip') }}</q-tooltip>
          </q-icon>
          <q-icon
            v-if="props.row.adminDisabledAccess"
            :name="icons.accessDisabled"
            color="negative"
            size="sm"
            class="q-ml-xs"
          >
            <q-tooltip>{{ $t('adminTools.accessDisabledTooltip') }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
    </q-table>
  </div>
</template>

<script lang="ts">
import icons from '@icons';
import formatMixin from '@mixins/formatMixin';
import { mapGetters } from 'vuex';
import MemberExportButtons from '@components/AdminTools/MemberExportButtons.vue';
import { MemberProfile } from 'types/member';
import { memberMatchesQuery } from '../../utils/fuzzySearch';
import { CsvColumn } from '../../utils/memberExport';
import { defineComponent } from 'vue';
import type { QInput } from 'quasar';

export default defineComponent({
  name: 'MembersList',
  components: { MemberExportButtons },
  mixins: [formatMixin],
  data() {
    return {
      members: [],
      loading: false,
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
    filter: {
      get(): string {
        return this.$store.getters['adminTools/membersFilter'];
      },
      // The clear button hands back null, but the store (and QTable's filter
      // prop) expect a string.
      set(value: string | null) {
        this.$store.commit('adminTools/setMembersFilter', value ?? '');
      },
    },
    memberState: {
      get(): string {
        return this.$store.getters['adminTools/membersState'];
      },
      set(value: string) {
        this.$store.commit('adminTools/setMembersState', value);
      },
    },
    pagination: {
      get() {
        return this.$store.getters['adminTools/membersPagination'];
      },
      set(value: object) {
        this.$store.commit('adminTools/setMembersPagination', value);
      },
    },
    displayMemberList() {
      if (this.memberState === 'all') return this.members;
      return this.members.filter(
        (member: MemberProfile) => member.state === this.memberState
      );
    },
    icons() {
      return icons;
    },
    filterOptions() {
      return [
        { label: this.$t('adminTools.all'), value: 'all' },
        { label: this.$t('adminTools.active'), value: 'active' },
        { label: this.$t('adminTools.inactive'), value: 'inactive' },
        { label: this.$t('adminTools.new'), value: 'noob' },
        { label: this.$t('adminTools.accountOnly'), value: 'accountonly' },
      ];
    },
    csvColumns(): CsvColumn<MemberProfile>[] {
      return [
        { header: this.$t('tableHeading.name'), value: (m) => m.name.full },
        {
          header: this.$t('tableHeading.screenName'),
          value: (m) => m.screenName,
        },
        { header: this.$t('tableHeading.email'), value: (m) => m.email },
        { header: this.$t('tableHeading.rfid'), value: (m) => m.rfid },
        ...(this.features?.signup?.collectVehicleRegistrationPlate
          ? [
              {
                header: this.$t('form.vehicleRegistrationPlate'),
                value: (m: MemberProfile) => m.vehicleRegistrationPlate,
              },
            ]
          : []),
        {
          header: this.$t('tableHeading.subscriptionStatus'),
          value: (m) =>
            this.$t(
              `adminTools.subscriptionStatusString.${m.subscriptionStatus}`
            ),
        },
        {
          header: this.$t('tableHeading.status'),
          value: (m) => this.$t(`adminTools.memberStatusString.${m.state}`),
        },
      ];
    },
    columns() {
      return [
        {
          name: 'name',
          label: this.$t('tableHeading.name'),
          field: (row: MemberProfile) => row.name.full,
          sortable: true,
          format: (val: string, row: MemberProfile) =>
            row.screenName ? `${val} (${row.screenName})` : val,
        },
        {
          name: 'rfid',
          label: this.$t('tableHeading.rfid'),
          field: 'rfid',
          sortable: true,
        },
        {
          name: 'email',
          label: this.$t('tableHeading.email'),
          field: 'email',
          sortable: true,
        },
        // this is weird syntax, but cleanest way to do it
        ...(this.features?.signup?.collectVehicleRegistrationPlate
          ? [
              {
                name: 'vehicleRegistration',
                label: this.$t('form.vehicleRegistrationPlate'),
                field: 'vehicleRegistrationPlate',
                sortable: true,
              },
            ]
          : []),
        {
          name: 'subscriptionStatus',
          label: this.$t('tableHeading.subscriptionStatus'),
          field: 'subscriptionStatus',
          sortable: true,
          format: (val: string) =>
            this.$t(`adminTools.subscriptionStatusString.${val}`),
        },
        {
          name: 'status',
          label: this.$t('tableHeading.status'),
          field: 'state',
          sortable: true,
          format: (val: string) =>
            this.$t(`adminTools.memberStatusString.${val}`),
        },
      ];
    },
  },
  created() {
    if (this.pagination.rowsPerPage === null) {
      this.pagination = {
        ...this.pagination,
        rowsPerPage: this.$q.screen.xs ? 3 : 10,
      };
    }
  },
  mounted() {
    this.getMembers();
    window.addEventListener('keydown', this.onKeydown);
  },
  beforeUnmount() {
    window.removeEventListener('keydown', this.onKeydown);
  },
  methods: {
    fuzzyFilter(rows: MemberProfile[], terms: string) {
      return rows.filter((row) => memberMatchesQuery(row, terms));
    },
    // Ctrl/Cmd+F jumps to the member search instead of the browser's find bar,
    // which can only see the current page of the table anyway. Typing in any
    // other field still gets native find.
    onKeydown(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) {
        return;
      }
      // Caps Lock reports 'F' even with shift up.
      if (event.key.toLowerCase() !== 'f') return;

      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) {
        return;
      }

      event.preventDefault();
      (this.$refs.searchInput as QInput | undefined)?.focus();
    },
    getMembers() {
      this.loading = true;
      this.$axios
        .get('/api/admin/members/')
        .then((response) => {
          this.members = response.data;
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('error.error'),
            message: this.$t('error.requestFailed'),
          });
        })
        .finally(() => {
          this.loading = false;
        });
    },
  },
});
</script>

<style scoped lang="scss">
.td {
  padding: 0;
}
</style>
