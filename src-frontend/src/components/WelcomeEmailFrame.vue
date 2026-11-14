<template>
  <iframe
    ref="frame"
    :srcdoc="emailDocument"
    :title="title"
    sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
    class="welcome-email-frame"
    @load="fitToContent"
  />
</template>

<script lang="ts">
import { defineComponent } from 'vue';

// The welcome email's HTML, shown as members receive it. The sandbox runs no
// scripts; allow-same-origin is only there so the frame can be sized to the
// email, which leaves no fixed height and no inner scrollbar.
export default defineComponent({
  name: 'WelcomeEmailFrame',
  props: {
    html: { type: String, required: true },
    title: { type: String, required: true },
  },
  data() {
    return {
      width: 0,
      observer: null as ResizeObserver | null,
    };
  },
  computed: {
    emailDocument(): string {
      // Links open in a new tab rather than inside the frame.
      const base = '<base target="_blank">';
      const head = /<head[^>]*>/i;
      return head.test(this.html)
        ? this.html.replace(head, (tag) => tag + base)
        : base + this.html;
    },
  },
  mounted() {
    // The email reflows at narrow widths, so refit when the width changes.
    this.observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width === this.width) return;
      this.width = entry.contentRect.width;
      this.fitToContent();
    });
    this.observer.observe(this.$refs.frame as HTMLIFrameElement);
  },
  beforeUnmount() {
    this.observer?.disconnect();
  },
  methods: {
    fitToContent() {
      const frame = this.$refs.frame as HTMLIFrameElement | undefined;
      const root = frame?.contentDocument?.documentElement;
      if (!frame || !root) return;
      // The email's body is height: 100%, so measure with the frame collapsed;
      // otherwise the frame's current height props the email up and it can
      // never shrink.
      frame.style.height = '0px';
      frame.style.height = `${root.scrollHeight}px`;
    },
  },
});
</script>

<style scoped>
.welcome-email-frame {
  display: block;
  width: 100%;
  height: 0;
  border: 0;
}
</style>
