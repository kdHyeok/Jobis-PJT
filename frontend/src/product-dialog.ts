import { reactive } from "vue";

export type ProductDialogOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  input?: { value: string; label: string; maxLength?: number };
};

type DialogState = ProductDialogOptions & {
  open: boolean;
  inputValue: string;
};

const state = reactive<DialogState>({
  open: false,
  title: "",
  message: "",
  confirmLabel: "확인",
  cancelLabel: "취소",
  danger: false,
  inputValue: "",
});

let resolver: ((value: boolean | string | null) => void) | null = null;

function open(options: ProductDialogOptions) {
  if (resolver) resolver(null);
  Object.assign(state, options, {
    open: true,
    input: options.input,
    inputValue: options.input?.value ?? "",
  });
  return new Promise<boolean | string | null>((resolve) => {
    resolver = resolve;
  });
}

function settle(value: boolean | string | null) {
  if (!state.open) return;
  state.open = false;
  const current = resolver;
  resolver = null;
  current?.(value);
}

export const productDialog = {
  state,
  confirm(options: ProductDialogOptions): Promise<boolean> {
    return open(options).then((value) => value === true);
  },
  prompt(options: ProductDialogOptions & { input: NonNullable<ProductDialogOptions["input"]> }): Promise<string | null> {
    return open(options).then((value) => typeof value === "string" ? value : null);
  },
  accept() {
    settle(state.input ? state.inputValue.trim() : true);
  },
  cancel() {
    settle(null);
  },
};
