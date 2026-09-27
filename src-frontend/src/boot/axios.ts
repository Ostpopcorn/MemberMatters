import axios, { AxiosInstance } from 'axios';
import { boot } from 'quasar/wrappers';

declare module '@vue/runtime-core' {
  interface ComponentCustomProperties {
    $axios: AxiosInstance;
  }
}

const api = axios.create({
  baseURL: process.env.apiBaseUrl || '',
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFTOKEN',
});

export default boot(({ app }) => {
  app.config.globalProperties.$axios = api;
});

export { api };
