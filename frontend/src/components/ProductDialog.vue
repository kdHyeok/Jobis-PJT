<script setup lang="ts">
import { X } from "@lucide/vue";
import { nextTick, onBeforeUnmount, ref, watch } from "vue";

import { productDialog } from "@/product-dialog";

const dialog = ref<HTMLElement | null>(null);
let trigger: HTMLElement | null = null;

watch(
  () => productDialog.state.open,
  async (open) => {
    if (open) {
      trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      await nextTick();
      const first = dialog.value?.querySelector<HTMLElement>("input, button, textarea, [tabindex]:not([tabindex='-1'])");
      first?.focus();
    } else {
      trigger?.focus();
      trigger = null;
    }
  },
);

function trapFocus(event: KeyboardEvent) {
  if (event.key !== "Tab" || !dialog.value) return;
  const items = [...dialog.value.querySelectorAll<HTMLElement>("input, button, textarea, [href], [tabindex]:not([tabindex='-1'])")]
    .filter((item) => !item.hasAttribute("disabled"));
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

onBeforeUnmount(() => {
  if (productDialog.state.open) productDialog.cancel();
});
</script>

<template>
  <Teleport to="body">
    <div v-if="productDialog.state.open" class="product-dialog-backdrop" @mousedown.self="productDialog.cancel">
      <section
        ref="dialog"
        class="product-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-dialog-title"
        tabindex="-1"
        @keydown.esc.prevent="productDialog.cancel"
        @keydown="trapFocus"
      >
        <header>
          <div>
            <p class="eyebrow">JOBIS CONFIRMATION</p>
            <h2 id="product-dialog-title">{{ productDialog.state.title }}</h2>
          </div>
          <button class="icon-button" type="button" aria-label="닫기" @click="productDialog.cancel"><X :size="19" /></button>
        </header>
        <p class="product-dialog__message">{{ productDialog.state.message }}</p>
        <label v-if="productDialog.state.input" class="product-dialog__input">
          <span>{{ productDialog.state.input.label }}</span>
          <input
            v-model="productDialog.state.inputValue"
            :maxlength="productDialog.state.input.maxLength ?? 180"
            @keydown.enter.prevent="productDialog.accept"
          />
        </label>
        <footer>
          <button class="press-button press-button--quiet" type="button" @click="productDialog.cancel">
            {{ productDialog.state.cancelLabel ?? '취소' }}
          </button>
          <button
            class="press-button"
            :class="productDialog.state.danger ? 'press-button--danger' : 'press-button--primary'"
            type="button"
            :disabled="Boolean(productDialog.state.input && !productDialog.state.inputValue.trim())"
            @click="productDialog.accept"
          >
            {{ productDialog.state.confirmLabel ?? '확인' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
