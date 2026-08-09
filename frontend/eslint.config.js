// 프론트 정적분석. CI 의 'Static analysis' 단계가 `npm run lint` 로 돌린다.
//
// 지금은 advisory(경고)다 — 기존 코드에 걸리는 항목이 남아 있어 처음부터 머지를 막으면
// 개발이 멈춘다. 정리한 뒤 Jenkinsfile 에서 catchError 를 걷어내 required 로 올린다.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import pluginVue from "eslint-plugin-vue";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "*.config.js"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  {
    // 브라우저에서 도는 코드다. window·setTimeout 등을 전역으로 인정한다.
    languageOptions: { globals: globals.browser },
  },
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: { parser: tseslint.parser },
    },
  },
  {
    // TS·Vue 에서는 미정의 식별자를 TypeScript 가 잡는다. no-undef 는 DOM 타입
    // (ScrollBehavior 같은)까지 미정의로 오인하므로 끈다 — typescript-eslint 권장.
    files: ["**/*.ts", "**/*.vue"],
    rules: { "no-undef": "off" },
  },
  {
    rules: {
      // 템플릿 속성 줄바꿈·순서 같은 서식 규칙은 이 저장소의 관심사가 아니다.
      "vue/max-attributes-per-line": "off",
      "vue/singleline-html-element-content-newline": "off",
      "vue/attributes-order": "off",
      "vue/html-self-closing": "off",
      "vue/html-indent": "off",
      // any 는 경계에서 불가피하게 쓰인다. 남용은 리뷰에서 잡는다.
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
);
