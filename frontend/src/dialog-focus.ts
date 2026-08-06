import type { Directive } from "vue";

type DialogBinding = {
  onEscape?: () => void;
};

const cleanup = new WeakMap<HTMLElement, () => void>();

function focusableItems(element: HTMLElement) {
  return [...element.querySelectorAll<HTMLElement>(
    "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], summary, [tabindex]:not([tabindex='-1'])",
  )].filter((item) => !item.hidden && item.getAttribute("aria-hidden") !== "true");
}

export const dialogFocus: Directive<HTMLElement, DialogBinding | undefined> = {
  mounted(element, binding) {
    const trigger = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && binding.value?.onEscape) {
        event.preventDefault();
        binding.value.onEscape();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusableItems(element);
      if (!items.length) {
        event.preventDefault();
        element.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    element.addEventListener("keydown", keydown);
    cleanup.set(element, () => {
      element.removeEventListener("keydown", keydown);
      trigger?.focus();
    });
    queueMicrotask(() => (focusableItems(element)[0] ?? element).focus());
  },
  unmounted(element) {
    cleanup.get(element)?.();
    cleanup.delete(element);
  },
};
