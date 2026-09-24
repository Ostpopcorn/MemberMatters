<template>
  <div style="max-width: 100%">
    <q-table
      :rows="filteredMembers"
      :no-data-label="$t('adminTools.noMembers')"
      :columns="columns"
      row-key="id"
      v-model:pagination="pagination"
      :loading="loading"
      :grid="grid"
      class="full-width"
      @row-click="(evt, row) => goToMember(row)"
    >
      <template v-slot:top>
        <div class="row items-start justify-between full-width">
          <q-select
            v-model="memberState"
            class="q-mr-sm q-mb-sm"
            style="min-width: 140px"
            outlined
            emit-value
            map-options
            :options="filterOptions"
            :label="$t('adminTools.filterOptions')"
            dense
          />

          <member-export-buttons
            :members="filteredMembers"
            :csv-columns="csvColumns"
          />
        </div>
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

      <template v-slot:item="props">
        <div class="q-pa-xs col-xs-12 col-sm-6 col-md-4 col-lg-3">
          <member-summary-card
            :member="props.row"
            @click="goToMember(props.row)"
          >
            <div v-if="props.row.rfid" class="text-caption">
              <q-icon :name="icons.rfid" class="q-mr-xs" />
              {{ props.row.rfid }}
            </div>
            <div
              v-if="
                features?.signup?.collectVehicleRegistrationPlate &&
                props.row.vehicleRegistrationPlate
              "
              class="text-caption"
            >
              {{ $t('form.vehicleRegistrationPlate') }}:
              {{ props.row.vehicleRegistrationPlate }}
            </div>
          </member-summary-card>
        </div>
      </template>
    </q-table>
  </div>
</template>

<script lang="ts">
import icons from '@icons';
import formatMixin from '@mixins/formatMixin';
import { mapGetters } from 'vuex';
import MemberExportButtons from '@components/AdminTools/MemberExportButtons.vue';
import MemberSummaryCard from '@components/AdminTools/MemberSummaryCard.vue';
import { MemberProfile } from 'types/member';
import { memberMatchesQuery } from '../../utils/fuzzySearch';
import { CsvColumn } from '../../utils/memberExport';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'MembersList',
  components: { MemberExportButtons, MemberSummaryCard },
  mixins: [formatMixin],
  props: {
    grid: {
      type: Boolean,
      default: false,
    },
    // Owned by the members page, which shares it with the signup tab.
    search: {
      type: String,
      default: '',
    },
  },
  data() {
    return {
      members: [] as MemberProfile[],
      loading: false,
    };
  },
  computed: {
    ...mapGetters('config', ['features']),
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
    // Filtered here rather than through QTable's filter so the exports get
    // exactly the rows on screen.
    filteredMembers(): MemberProfile[] {
      return this.members.filter(
        (member: MemberProfile) =>
          (this.memberState === 'all' || member.state === this.memberState) &&
          memberMatchesQuery(member, this.search)
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
  },
  methods: {
    goToMember(member: MemberProfile) {
      this.$router.push({
        name: 'manageMember',
        params: { memberId: member.id },
      });
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
