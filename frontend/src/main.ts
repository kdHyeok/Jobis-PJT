import "@fontsource-variable/nunito";
import "pretendard/dist/web/variable/pretendardvariable.css";
import "@/styles/base.css";
import "@/styles/jobis-theme.css";

import { createApp } from "vue";

import App from "@/App.vue";
import { dialogFocus } from "@/dialog-focus";
import { router } from "@/router";

createApp(App).directive("dialog-focus", dialogFocus).use(router).mount("#app");
