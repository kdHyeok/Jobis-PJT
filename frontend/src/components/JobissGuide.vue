<script setup lang="ts">
defineProps<{ message: string }>();
</script>

<template>
  <div class="guide">
    <div class="guide-character" aria-hidden="true">
      <span class="guide-antenna" />
      <span class="guide-eye guide-eye--left" />
      <span class="guide-eye guide-eye--right" />
      <span class="guide-smile" />
    </div>
    <p>{{ message }}</p>
  </div>
</template>
