import { computed, reactive } from "vue";

import { api } from "@/api";
import type { User } from "@/types";

const state = reactive<{
  user: User | null;
  restored: boolean;
}>({
  user: null,
  restored: false,
});

let restorePromise: Promise<void> | null = null;

async function restore(): Promise<void> {
  if (state.restored) return;
  if (!restorePromise) {
    restorePromise = api
      .me()
      .then((user) => {
        state.user = user;
      })
      .catch(() => {
        state.user = null;
      })
      .finally(() => {
        state.restored = true;
      });
  }
  await restorePromise;
}

export const session = {
  state,
  user: computed(() => state.user),
  authenticated: computed(() => Boolean(state.user)),
  restore,
  setUser(user: User) {
    state.user = user;
    state.restored = true;
  },
  clear() {
    state.user = null;
    state.restored = true;
  },
};
