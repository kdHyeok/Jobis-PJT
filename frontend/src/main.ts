import "pretendard/dist/web/variable/pretendardvariable.css";
import "@/styles/base.css";

import { createApp } from "vue";

import App from "@/App.vue";
import { router } from "@/router";

createApp(App).use(router).mount("#app");
